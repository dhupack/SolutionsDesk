from __future__ import annotations   # defer annotation eval so build-only pandas can be imported lazily

import logging
import json
from pathlib import Path
from typing import Dict, List, Tuple
import faiss
import numpy as np
# NOTE: pandas is imported lazily inside the build-time methods below. It is only
# needed to read the feature Excel sheets when (re)building the index, never to
# serve queries — keeping it out of the import path saves ~40MB at runtime.

from config import (
    FEATURE_SHEET_DIR,
    FEATURE_SHEET_NAME,
    FEATURE_COLUMNS,
    FEATURE_FAISS_INDEX_PATH,
    FEATURE_METADATA_PATH,
    FEATURE_SHEET_XLSX_URL,
    FEATURE_SHEET_TABS,
    FEATURE_SHEET_GSHEET_ID,
    FEATURE_SHEET_TAB_GIDS,
    get_embeddings,
)

logger = logging.getLogger(__name__)


class FeatureLoader:

    def __init__(self):
        self.embeddings = get_embeddings()
        self.faiss_index = None
        self.metadata = []
        self.features_df = None
        # Bucket -> [metadata positions], for same-bucket sibling rollup
        self._bucket_map = {}

    def _find_sheet(self, excel_file) -> str:
        import pandas as pd
        xl = pd.ExcelFile(excel_file)
        for sheet in xl.sheet_names:
            if sheet.lower() == FEATURE_SHEET_NAME.lower():
                return sheet
        return None

    def load_from_gsheet_csv(self) -> List[Dict]:
        """Pull the catalogue from the Google Sheet using the per-tab CSV export and
        the stdlib `csv` module — NO pandas/openpyxl. This keeps a server-side rebuild
        well under Render's 512MB limit (importing pandas at runtime OOM-killed the
        worker). Returns a list of plain row dicts, each tagged with its source tab and
        per-tab row number. Empty list on any failure (caller falls back to Excel).
        """
        import csv as _csv
        import io
        import urllib.request

        if not FEATURE_SHEET_GSHEET_ID:
            return []
        rows: List[Dict] = []
        for tab, gid in (FEATURE_SHEET_TAB_GIDS or {}).items():
            url = (f"https://docs.google.com/spreadsheets/d/{FEATURE_SHEET_GSHEET_ID}"
                   f"/export?format=csv&gid={gid}")
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    text = resp.read().decode("utf-8")
            except Exception as e:
                logger.error(f"Failed to pull tab '{tab}' (gid={gid}): {e}")
                return []   # all-or-nothing: don't build a partial index
            reader = _csv.DictReader(io.StringIO(text))
            count = 0
            for i, row in enumerate(reader):
                if not any((v or "").strip() for v in row.values()):
                    continue   # skip blank rows
                row["_source_tab"] = tab
                row["_row_number"] = i + 2   # +1 header, +1 to 1-based
                rows.append(row)
                count += 1
            logger.info(f"Pulled {count} features from tab '{tab}' (gid={gid}) via CSV")
        return rows

    def prepare_feature_texts_from_rows(self, rows: List[Dict]) -> List[Tuple[str, Dict]]:
        """pandas-free equivalent of prepare_feature_texts() for plain CSV row dicts."""
        feature_texts = []
        for row in rows:
            def get(col):
                v = str(row.get(col, "") or "").strip()
                return "" if v.lower() == "nan" else v

            name   = get("Feature Name")
            what   = get("What it does")
            value  = get("Business Value / Impact")
            deps   = get("Dependencies / Inputs")
            sales  = get("Sales Talking Point")
            module = get("Module / Area")
            bucket = get("Bucket")

            combined_text = (
                f"{name}. {name}. "
                f"This feature is about {module} in the {bucket} area. "
                f"What it does: {what}. "
                f"Business value: {value}. "
                f"Sales context: {sales}. "
                f"Requires: {deps}."
            )
            full_row = {k: v for k, v in row.items() if k not in ("_source_tab", "_row_number")}
            metadata = {
                "feature_id": str(row.get("Feature ID", "")),
                "feature_name": name,
                "row_number": row.get("_row_number"),
                "source_file": row.get("_source_tab", "Feature_catalogue.xlsx"),
                "full_row": full_row,
            }
            feature_texts.append((combined_text, metadata))
        return feature_texts

    def load_from_gsheet(self) -> pd.DataFrame:
        """Pull the feature catalogue from the configured Google Sheet.

        Downloads the whole workbook once as .xlsx (export?format=xlsx) and reads
        the configured tabs by name. Returns an empty DataFrame on any failure so
        the caller can fall back to the committed/local index.
        """
        import pandas as pd
        from io import BytesIO
        import urllib.request

        if not FEATURE_SHEET_XLSX_URL:
            return pd.DataFrame()
        try:
            logger.info(f"Pulling feature catalogue from Google Sheet: {FEATURE_SHEET_XLSX_URL}")
            req = urllib.request.Request(FEATURE_SHEET_XLSX_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()
            all_tabs = pd.read_excel(BytesIO(content), sheet_name=None)  # {tab_name: df}
        except Exception as e:
            logger.error(f"Failed to pull Google Sheet: {e}")
            return pd.DataFrame()

        wanted = FEATURE_SHEET_TABS or list(all_tabs.keys())
        dfs = []
        for tab in wanted:
            df = all_tabs.get(tab)
            if df is None:
                logger.warning(f"Tab '{tab}' not found in workbook (have: {list(all_tabs.keys())}), skipping")
                continue
            df = df.dropna(how="all")
            df["_source_tab"] = tab            # keep provenance for citations
            logger.info(f"Pulled {len(df)} features from tab '{tab}'")
            dfs.append(df)

        if not dfs:
            return pd.DataFrame()
        combined = pd.concat(dfs, ignore_index=True)
        self.features_df = combined
        return combined

    def load_feature_sheets(self) -> pd.DataFrame:
        import pandas as pd
        # Production source of truth is the Google Sheet; fall back to local Excel.
        gsheet_df = self.load_from_gsheet()
        if not gsheet_df.empty:
            return gsheet_df

        excel_files = list(FEATURE_SHEET_DIR.glob("*.xlsx")) + list(FEATURE_SHEET_DIR.glob("*.xls"))
        if not excel_files:
            logger.warning(f"No Excel files found in {FEATURE_SHEET_DIR}")
            return pd.DataFrame()

        dfs = []
        for excel_file in excel_files:
            try:
                sheet_name = self._find_sheet(excel_file)
                if not sheet_name:
                    logger.warning(f"No 'Feature catalogue' sheet in {excel_file.name}, skipping")
                    continue
                df = pd.read_excel(excel_file, sheet_name=sheet_name)
                logger.info(f"Loaded {len(df)} features from {excel_file.name} (sheet: {sheet_name})")
                dfs.append(df)
            except Exception as e:
                logger.error(f"Error loading {excel_file.name}: {e}")

        if dfs:
            combined = pd.concat(dfs, ignore_index=True)
            self.features_df = combined
            return combined
        return pd.DataFrame()

    def prepare_feature_texts(self, df: pd.DataFrame) -> List[Tuple[str, Dict]]:
        import pandas as pd
        feature_texts = []
        for idx, row in df.iterrows():
            def get(col):
                v = row.get(col, "")
                return str(v).strip() if pd.notna(v) and str(v).strip() not in ("nan", "") else ""

            name    = get("Feature Name")
            what    = get("What it does")
            value   = get("Business Value / Impact")
            deps    = get("Dependencies / Inputs")
            sales   = get("Sales Talking Point")
            module  = get("Module / Area")
            bucket  = get("Bucket")

            # Natural language description — feature name repeated for weight,
            # focused on problem-solving language so queries match better
            combined_text = (
                f"{name}. {name}. "
                f"This feature is about {module} in the {bucket} area. "
                f"What it does: {what}. "
                f"Business value: {value}. "
                f"Sales context: {sales}. "
                f"Requires: {deps}."
            )

            source_tab = get("_source_tab") or "Feature_catalogue.xlsx"
            full_row = row.to_dict()
            full_row.pop("_source_tab", None)   # internal provenance column, not catalogue data
            metadata = {
                "feature_id": str(row.get("Feature ID", "")),
                "feature_name": name,
                "row_number": idx + 2,
                "source_file": source_tab,
                "full_row": full_row
            }
            feature_texts.append((combined_text, metadata))
        return feature_texts

    def create_embeddings(self, texts: List[Tuple[str, Dict]]):
        text_only = [t[0] for t in texts]
        logger.info(f"Embedding {len(text_only)} features...")
        embeddings_list = self.embeddings.embed_documents(text_only)
        embeddings_array = np.array(embeddings_list).astype('float32')

        # Normalize for cosine similarity via inner product
        faiss.normalize_L2(embeddings_array)

        dimension = embeddings_array.shape[1]
        index = faiss.IndexFlatIP(dimension)  # Inner product = cosine on normalized vectors
        index.add(embeddings_array)

        self.metadata = [t[1] for t in texts]
        self.faiss_index = index
        self._build_bucket_map()
        logger.info(f"Feature FAISS index created: {len(embeddings_list)} vectors, dim={dimension}")
        return index

    @staticmethod
    def _bucket_of(meta: Dict) -> str:
        return str((meta.get("full_row") or {}).get("Bucket", "")).strip()

    def _build_bucket_map(self):
        """Index Bucket -> [metadata positions] so a hit can pull its bucket-mates."""
        self._bucket_map = {}
        for i, m in enumerate(self.metadata):
            b = self._bucket_of(m)
            if b:
                self._bucket_map.setdefault(b, []).append(i)

    def save_index(self):
        FEATURE_FAISS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.faiss_index, str(FEATURE_FAISS_INDEX_PATH))
        with open(FEATURE_METADATA_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, default=str)
        logger.info("Feature index saved")

    def load_index(self):
        if FEATURE_FAISS_INDEX_PATH.exists():
            self.faiss_index = faiss.read_index(str(FEATURE_FAISS_INDEX_PATH))
        if FEATURE_METADATA_PATH.exists():
            with open(FEATURE_METADATA_PATH, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
        self._build_bucket_map()
        logger.info(f"Feature index loaded: {len(self.metadata)} features")

    def search_vec(self, query_embedding, k: int = 3) -> List[Dict]:
        """Search using a pre-computed query vector (lets the caller embed once)."""
        if self.faiss_index is None or not self.metadata:
            return []
        qe = np.array(query_embedding).astype('float32').reshape(1, -1)
        faiss.normalize_L2(qe)  # Normalize query for cosine similarity
        scores, indices = self.faiss_index.search(qe, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if 0 <= idx < len(self.metadata):
                results.append({
                    "similarity_score": float(score),  # Already in [0,1] range after normalization
                    "metadata": self.metadata[idx]
                })
        return results

    def search_vec_grouped(self, query_embedding, k: int = 15,
                           max_buckets: int = 3, max_siblings: int = 8) -> List[Dict]:
        """Top-k search, then level-1 bucket rollup: for the strongest hits, pull in
        the other features that share the hit's Bucket (a metadata lookup, NOT bounded
        by k) so a query that lands in one area gets that area's full toolkit. Original
        hits keep their score; bucket-mates are tagged is_sibling=True."""
        hits = self.search_vec(query_embedding, k=k)
        if not hits:
            return hits
        seen = {id(h["metadata"]) for h in hits}
        ordered = list(hits)
        buckets_done = set()
        for h in hits:
            if len(buckets_done) >= max_buckets:
                break
            b = self._bucket_of(h["metadata"])
            if not b or b in buckets_done:
                continue
            positions = self._bucket_map.get(b, [])
            if len(positions) <= 1:
                continue
            buckets_done.add(b)
            for pos in positions[:max_siblings]:
                meta = self.metadata[pos]
                if id(meta) in seen:
                    continue
                seen.add(id(meta))
                ordered.append({"similarity_score": h["similarity_score"],
                                "is_sibling": True, "bucket": b, "metadata": meta})
        return ordered

    def search(self, query_text: str, k: int = 3) -> List[Dict]:
        if self.faiss_index is None or not self.metadata:
            return []
        return self.search_vec(self.embeddings.embed_query(query_text), k)

    def build_and_save(self) -> bool:
        # Primary: pandas-free CSV pull from the Google Sheet (memory-light, used on Render).
        rows = self.load_from_gsheet_csv()
        if rows:
            texts = self.prepare_feature_texts_from_rows(rows)
        else:
            # Fallback (dev): pandas/Excel path — local files or the xlsx workbook.
            df = self.load_feature_sheets()
            if df.empty:
                return False
            texts = self.prepare_feature_texts(df)
        if not texts:
            return False
        self.create_embeddings(texts)
        self.save_index()
        logger.info(f"Feature index built with {len(self.metadata)} features")
        return True

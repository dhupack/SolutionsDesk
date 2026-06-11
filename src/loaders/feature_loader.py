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
    get_embeddings,
)

logger = logging.getLogger(__name__)


class FeatureLoader:

    def __init__(self):
        self.embeddings = get_embeddings()
        self.faiss_index = None
        self.metadata = []
        self.features_df = None

    def _find_sheet(self, excel_file) -> str:
        import pandas as pd
        xl = pd.ExcelFile(excel_file)
        for sheet in xl.sheet_names:
            if sheet.lower() == FEATURE_SHEET_NAME.lower():
                return sheet
        return None

    def load_feature_sheets(self) -> pd.DataFrame:
        import pandas as pd
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

            metadata = {
                "feature_id": str(row.get("Feature ID", "")),
                "feature_name": name,
                "row_number": idx + 2,
                "source_file": "Feature_catalogue.xlsx",
                "full_row": row.to_dict()
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
        logger.info(f"Feature FAISS index created: {len(embeddings_list)} vectors, dim={dimension}")
        return index

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

    def search(self, query_text: str, k: int = 3) -> List[Dict]:
        if self.faiss_index is None or not self.metadata:
            return []
        return self.search_vec(self.embeddings.embed_query(query_text), k)

    def build_and_save(self) -> bool:
        df = self.load_feature_sheets()
        if df.empty:
            return False
        texts = self.prepare_feature_texts(df)
        self.create_embeddings(texts)
        self.save_index()
        logger.info(f"Feature index built with {len(self.metadata)} features")
        return True

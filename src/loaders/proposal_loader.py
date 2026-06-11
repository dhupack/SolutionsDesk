import re
import logging
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import faiss
import numpy as np
import PyPDF2
from pptx import Presentation
from docx import Document

from config import (
    RAW_PROPOSALS_DIR,
    PROPOSAL_FAISS_INDEX_PATH,
    PROPOSAL_METADATA_PATH,
    get_embeddings,
)

logger = logging.getLogger(__name__)

# ── Boilerplate paragraph detection ────────────────────────────────────────────
_BOILERPLATE_RE = re.compile(
    r'\.{5,}'                               # TOC dots
    r'|Page \| \d+'                         # "Page | 12"
    r'|Copyright ©'                         # footer
    r'|Axestrack Software Solutions Pvt'    # address block
    r'|Gopalpura bypass'
    r'|Office No\.'
    r'|Submitted on\s*[–\-]'               # cover page date
    r'|W\d+\s+[•\-]\s+\w'                 # project timeline rows
    r'|^\s*\d+\s*$',                        # lone page numbers
    re.IGNORECASE | re.MULTILINE
)

# ── Industry classification ─────────────────────────────────────────────────────
# Client name → industry. Checked FIRST — the folder/company name is the most
# reliable signal. Order matters: more specific names before generic ones.
_CLIENT_INDUSTRY = [
    ('amns',           'steel'),
    ('arcelormittal',  'steel'),
    ('kattupalli',     'port'),
    ('ennore',         'port'),
    ('abg trading',    'port'),
    ('bajel',          'port'),
    ('ashok leyland',  'automotive'),
    ('ather',          'automotive'),
    ('apcotex',        'chemical'),
    ('atul',           'chemical'),
    ('amar raja',      'battery'),
    ('amazon',         'ecommerce'),
    ('asahi',          'glass'),
    ('ashai',          'glass'),
    ('adani',          'conglomerate'),  # generic Adani — checked after kattupalli/ennore
]

# Content keywords → industry. Checked only if the client name does not resolve.
# Matched with word boundaries so "port" never matches "transport"/"export"/"report".
_CONTENT_INDUSTRY = {
    'steel':      ['steel plant', 'hazira', 'marshalling yard', 'rolling mill'],
    'port':       ['vessel', 'berth', 'barge', 'jetty', 'coal shipment', 'navis', 'stevedoring'],
    'automotive': ['electric vehicle', 'automobile', 'oem'],
    'chemical':   ['chemical', 'polymer', 'latex', 'hazmat', 'hazardous material'],
    'ecommerce':  ['last-mile', 'last mile', 'delivery hub', 'e-commerce'],
    'battery':    ['battery', 'energy storage'],
    'glass':      ['glass'],
    'mining':     ['mine', 'mining', 'mineral'],
}

def _detect_industry(text: str, client_name: str) -> str:
    cl = client_name.lower()
    # 1. Strongest signal: client/company name maps directly to an industry
    for name, industry in _CLIENT_INDUSTRY:
        if name in cl:
            return industry
    # 2. Fall back to content keywords with WORD-BOUNDARY matching
    #    (so "port" matches the standalone word, never inside "transport"/"export")
    body = text[:2000].lower()
    for industry, kws in _CONTENT_INDUSTRY.items():
        for kw in kws:
            if re.search(r'\b' + re.escape(kw) + r'\b', body):
                return industry
    return 'logistics'


def _is_boilerplate(para: str) -> bool:
    if _BOILERPLATE_RE.search(para):
        return True
    if len(para) > 10 and para.count('.') / len(para) > 0.25:
        return True
    if 'axestrack has been recognized' in para.lower() and 'gartner' in para.lower():
        return True
    return False


def _clean_text(text: str) -> str:
    text = re.sub(r'\s{3,}', '  ', text)
    text = re.sub(r'-\s*\n\s*', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _split_into_chunks(paragraphs: List[str], target_words: int = 300, overlap: int = 1) -> List[str]:
    chunks, i = [], 0
    while i < len(paragraphs):
        chunk_paras, word_count, j = [], 0, i
        while j < len(paragraphs) and word_count < target_words:
            chunk_paras.append(paragraphs[j])
            word_count += len(paragraphs[j].split())
            j += 1
        text = '\n\n'.join(chunk_paras).strip()
        if len(text) > 100:
            chunks.append(text)
        i = max(i + 1, j - overlap)
    return chunks


def _split_paged(para_page: List[Tuple[str, str]], target_words: int = 300, overlap: int = 1):
    """
    Like _split_into_chunks but carries a page reference.
    Input:  list of (paragraph, page_ref) where page_ref is e.g. 'p.5', 'slide 3', or ''.
    Output: list of (chunk_text, page_ref_of_first_paragraph_in_chunk).
    """
    chunks, i = [], 0
    while i < len(para_page):
        chunk_paras, word_count, j = [], 0, i
        while j < len(para_page) and word_count < target_words:
            chunk_paras.append(para_page[j][0])
            word_count += len(para_page[j][0].split())
            j += 1
        text = '\n\n'.join(chunk_paras).strip()
        if len(text) > 100:
            chunks.append((text, para_page[i][1]))
        i = max(i + 1, j - overlap)
    return chunks


def _extract_pdf(file_path: Path) -> List[Tuple[str, int]]:
    pages = []
    try:
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                if text.strip():
                    pages.append((_clean_text(text), i))
    except Exception as e:
        logger.error(f"PDF extraction failed for {file_path.name}: {e}")
    return pages


def _extract_ppt(file_path: Path) -> List[Tuple[str, int]]:
    slides = []
    try:
        prs = Presentation(file_path)
        for i, slide in enumerate(prs.slides, 1):
            texts = []
            for shape in slide.shapes:
                if hasattr(shape, 'text') and shape.text.strip():
                    texts.append(shape.text.strip())
            text = '\n'.join(texts)
            if len(text.strip()) > 50:
                slides.append((_clean_text(text), i))
    except Exception as e:
        logger.error(f"PPT extraction failed for {file_path.name}: {e}")
    return slides


def _extract_word(file_path: Path) -> List[Tuple[str, str]]:
    sections = []
    try:
        doc = Document(file_path)
        current_heading = "Introduction"
        current_paras = []

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name.lower() if para.style else ''
            is_heading = 'heading' in style

            if is_heading and current_paras:
                content = '\n'.join(current_paras)
                if len(content) > 100:
                    sections.append((_clean_text(content), current_heading))
                current_heading = text
                current_paras = []
            elif is_heading:
                current_heading = text
            else:
                current_paras.append(text)

        if current_paras:
            content = '\n'.join(current_paras)
            if len(content) > 100:
                sections.append((_clean_text(content), current_heading))

    except Exception as e:
        logger.error(f"Word extraction failed for {file_path.name}: {e}")
    return sections


class ProposalLoader:

    def __init__(self):
        self.embeddings = get_embeddings()
        self.faiss_index = None
        self.metadata = []

    def load_raw_documents(self) -> List[Tuple[str, Dict]]:
        """
        Read directly from data/raw_proposals/ subfolders.
        Folder name = client name. Supports PDF, PPT/PPTX, DOC/DOCX.
        Returns list of (chunk_text, metadata).
        """
        all_chunks = []
        supported = {'.pdf', '.ppt', '.pptx', '.doc', '.docx'}

        client_dirs = [d for d in RAW_PROPOSALS_DIR.iterdir() if d.is_dir()]
        if not client_dirs:
            logger.warning(f"No client folders found in {RAW_PROPOSALS_DIR}")
            return []

        for client_dir in sorted(client_dirs):
            client_name = client_dir.name

            for file_path in sorted(client_dir.rglob('*')):
                if file_path.suffix.lower() not in supported:
                    continue

                ext = file_path.suffix.lower()
                file_chunks = []   # list of (chunk_text, page_ref)

                try:
                    if ext == '.pdf':
                        # Keep page number with each paragraph so chunks can cite a page
                        pages = _extract_pdf(file_path)
                        para_page = []
                        for page_text, page_num in pages:
                            for p in re.split(r'\n{2,}', page_text):
                                p = p.strip()
                                if p and not _is_boilerplate(p) and len(p) > 60:
                                    para_page.append((p, f"p.{page_num}"))
                        file_chunks = _split_paged(para_page, target_words=300, overlap=1)

                    elif ext in ('.ppt', '.pptx'):
                        slides = _extract_ppt(file_path)
                        for slide_text, slide_num in slides:
                            if not _is_boilerplate(slide_text) and len(slide_text) > 60:
                                file_chunks.append((slide_text, f"slide {slide_num}"))

                    elif ext in ('.doc', '.docx'):
                        # Word has no reliable page numbers → empty page ref (cite doc name)
                        sections = _extract_word(file_path)
                        for section_text, heading in sections:
                            paragraphs = [p.strip() for p in re.split(r'\n{2,}', section_text) if p.strip()]
                            good_paras = [(p, "") for p in paragraphs if not _is_boilerplate(p) and len(p) > 60]
                            file_chunks.extend(_split_paged(good_paras, target_words=300, overlap=1))

                except Exception as e:
                    logger.error(f"Failed processing {file_path.name}: {e}")
                    continue

                if not file_chunks:
                    logger.info(f"No usable chunks from {file_path.name}")
                    continue

                sample_text = ' '.join(t for t, _ in file_chunks[:3])
                industry = _detect_industry(sample_text, client_name)

                for idx, (chunk_text, page_ref) in enumerate(file_chunks):
                    embed_text = (
                        f"Client: {client_name} | Industry: {industry} | "
                        f"File: {file_path.name}:\n\n{chunk_text}"
                    )
                    meta = {
                        "client_name": client_name,
                        "filename": file_path.name,
                        "file_type": ext.lstrip('.'),
                        "source_file": str(file_path),
                        "industry": industry,
                        "page_ref": page_ref,          # 'p.5' / 'slide 3' / '' for Word
                        "chunk_index": idx,
                        "word_count": len(chunk_text.split()),
                        "content": chunk_text,
                    }
                    all_chunks.append((embed_text, meta))

                logger.info(f"  {file_path.name} -> {len(file_chunks)} chunks")

        logger.info(f"Total proposal chunks from raw files: {len(all_chunks)}")
        return all_chunks

    def create_embeddings(self, chunks: List[Tuple[str, Dict]]):
        text_only = [c[0] for c in chunks]
        logger.info(f"Embedding {len(text_only)} proposal chunks...")
        embeddings_list = self.embeddings.embed_documents(text_only)
        embeddings_array = np.array(embeddings_list).astype('float32')
        faiss.normalize_L2(embeddings_array)
        dimension = embeddings_array.shape[1]
        index = faiss.IndexFlatIP(dimension)
        index.add(embeddings_array)
        self.metadata = [c[1] for c in chunks]
        self.faiss_index = index
        logger.info(f"Proposal FAISS index: {len(embeddings_list)} vectors, dim={dimension}")
        return index

    def save_index(self):
        PROPOSAL_FAISS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.faiss_index, str(PROPOSAL_FAISS_INDEX_PATH))
        with open(PROPOSAL_METADATA_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, default=str)
        logger.info("Proposal index saved")

    def load_index(self):
        if PROPOSAL_FAISS_INDEX_PATH.exists():
            self.faiss_index = faiss.read_index(str(PROPOSAL_FAISS_INDEX_PATH))
        if PROPOSAL_METADATA_PATH.exists():
            with open(PROPOSAL_METADATA_PATH, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
        logger.info(f"Proposal index loaded: {len(self.metadata)} chunks")

    def search_vec(self, query_embedding, k: int = 3) -> List[Dict]:
        """Search using a pre-computed query vector (lets the caller embed once)."""
        if self.faiss_index is None or not self.metadata:
            return []
        qe = np.array(query_embedding).astype('float32').reshape(1, -1)
        faiss.normalize_L2(qe)
        scores, indices = self.faiss_index.search(qe, k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if 0 <= idx < len(self.metadata):
                results.append({
                    "similarity_score": float(score),
                    "metadata": self.metadata[idx]
                })
        return results

    def search(self, query_text: str, k: int = 3) -> List[Dict]:
        if self.faiss_index is None or not self.metadata:
            return []
        return self.search_vec(self.embeddings.embed_query(query_text), k)

    def build_and_save(self) -> bool:
        chunks = self.load_raw_documents()
        if not chunks:
            logger.warning("No chunks extracted from raw proposal files")
            return False
        self.create_embeddings(chunks)
        self.save_index()
        return True

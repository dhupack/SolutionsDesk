"""RAG Pipeline source code."""

# The extraction pipeline (ExtractionPipeline, DocumentParser, …) is intentionally
# NOT imported here: it pulls in heavy, build-only deps (PyPDF2, python-pptx,
# python-docx, gdown) that the web app never needs to serve queries. Import it
# directly from src.extraction.* when building indexes (see setup.py).
from src.loaders import FeatureLoader, ProposalLoader
from src.retrieval import TierRetrieval
from src.rag import RAGWorkflow

__all__ = [
    "FeatureLoader",
    "ProposalLoader",
    "TierRetrieval",
    "RAGWorkflow",
]

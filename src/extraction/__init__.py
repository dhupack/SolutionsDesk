"""Extraction module — downloads proposal documents from Google Drive.

Parsing/embedding of those files is handled directly by
src/loaders/proposal_loader.py; this package only fetches the sources.
"""

from src.extraction.extraction_pipeline import ExtractionPipeline

__all__ = ["ExtractionPipeline"]

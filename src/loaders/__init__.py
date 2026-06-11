"""Loaders module for loading and embedding data sources."""

from src.loaders.feature_loader import FeatureLoader
from src.loaders.proposal_loader import ProposalLoader

__all__ = [
    "FeatureLoader",
    "ProposalLoader"
]

#!/usr/bin/env python
"""
Setup script for RAG pipeline initialization.
- Downloads proposal documents from Google Drive (if not already present)
- Builds FAISS indices for features and proposals directly from raw files
"""

import logging
import sys
from pathlib import Path

from src.loaders.feature_loader import FeatureLoader
from src.loaders.proposal_loader import ProposalLoader
from config import (
    RAW_PROPOSALS_DIR,
    FEATURE_SHEET_DIR,
    GOOGLE_DRIVE_FOLDER_ID
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('setup.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

logger = logging.getLogger(__name__)


def step1_download_proposals():
    """
    Step 1: Download proposal documents from Google Drive.
    Skipped automatically if files already exist in data/raw_proposals/.
    """
    print("\n" + "=" * 80)
    print("STEP 1: Download Proposal Documents from Google Drive")
    print("=" * 80)

    supported = ['.pdf', '.pptx', '.ppt', '.docx', '.doc']
    existing = [f for f in RAW_PROPOSALS_DIR.rglob("*") if f.is_file() and f.suffix.lower() in supported]
    if existing:
        print(f"Found {len(existing)} proposal files already in data/raw_proposals/ — skipping download.")
        return True

    cookies_file = Path(__file__).parent / "gdrive_cookies.txt"
    if not cookies_file.exists():
        print("\n  gdrive_cookies.txt not found!")
        print("The Google Drive folder is private. To download automatically:")
        print("  1. Install 'Get cookies.txt LOCALLY' extension in Chrome")
        print("  2. Open drive.google.com while logged in to your Google account")
        print("  3. Click the extension icon and export cookies for drive.google.com")
        print(f"  4. Save the file as: {cookies_file}")
        print("  5. Re-run: python setup.py")
        return False

    try:
        from src.extraction.extraction_pipeline import ExtractionPipeline
        pipeline = ExtractionPipeline()
        pipeline.download_from_gdrive()
        downloaded = list(RAW_PROPOSALS_DIR.rglob("*.*"))
        if downloaded:
            print(f"Downloaded {len(downloaded)} files to data/raw_proposals/")
            return True
        else:
            print("Download ran but no files found — check the Drive folder ID and cookie validity")
            return False
    except Exception as e:
        logger.error(f"Download error: {e}")
        print(f"\nDownload failed: {e}")
        return False


def step2_build_feature_index():
    """
    Step 2: Build FAISS index for feature sheet Excel files.
    """
    print("\n" + "=" * 80)
    print("STEP 2: Build FAISS Index for Feature Sheet")
    print("=" * 80)

    excel_files = list(FEATURE_SHEET_DIR.glob("*.xlsx")) + list(FEATURE_SHEET_DIR.glob("*.xls"))
    if not excel_files:
        logger.warning(f"No Excel files found in {FEATURE_SHEET_DIR}")
        print("Please upload your feature Excel files to:")
        print(f"  {FEATURE_SHEET_DIR}")
        return False

    logger.info(f"Found {len(excel_files)} Excel files")

    try:
        feature_loader = FeatureLoader()
        if feature_loader.build_and_save():
            logger.info(f"Feature index built with {len(feature_loader.metadata)} features")
            print(f"Feature FAISS index created successfully")
            return True
        else:
            logger.error("Failed to build feature index")
            return False
    except Exception as e:
        logger.error(f"Error building feature index: {e}")
        return False


def step3_build_proposal_index():
    """
    Step 3: Build FAISS index directly from raw proposal files (PDF/PPT/Word).
    No markdown extraction step needed.
    """
    print("\n" + "=" * 80)
    print("STEP 3: Build FAISS Index for Proposal Documents (from raw files)")
    print("=" * 80)

    supported = ['.pdf', '.pptx', '.ppt', '.docx', '.doc']
    raw_files = [f for f in RAW_PROPOSALS_DIR.rglob("*") if f.is_file() and f.suffix.lower() in supported]

    if not raw_files:
        logger.warning(f"No proposal files found in {RAW_PROPOSALS_DIR}")
        print("Run STEP 1 to download files first, or place proposal files in data/raw_proposals/")
        return False

    logger.info(f"Found {len(raw_files)} raw proposal files")

    try:
        proposal_loader = ProposalLoader()
        if proposal_loader.build_and_save():
            logger.info(f"Proposal index built with {len(proposal_loader.metadata)} chunks")
            print(f"Proposal FAISS index created successfully")
            return True
        else:
            logger.error("Failed to build proposal index")
            return False
    except Exception as e:
        logger.error(f"Error building proposal index: {e}")
        return False


def main():
    print("\n" + "=" * 80)
    print("RAG PIPELINE SETUP")
    print("=" * 80)

    steps = [
        ("Download Proposals",  step1_download_proposals,  False),
        ("Build Feature Index", step2_build_feature_index, True),
        ("Build Proposal Index", step3_build_proposal_index, False),
    ]

    results = {}

    for step_name, step_func, critical in steps:
        success = step_func()
        results[step_name] = success

        if not success and critical:
            logger.warning(f"Critical step '{step_name}' failed. Stopping setup.")
            print(f"\nPlease fix the issue and run setup again.")
            break

    print("\n" + "=" * 80)
    print("SETUP SUMMARY")
    print("=" * 80)

    for step_name, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  [{status}] {step_name}")

    all_critical_passed = all(results.get(name, False) for name, _, critical in steps if critical)

    if all_critical_passed:
        print("\nSetup completed. You can now run:")
        print("   python app_new.py")
    else:
        print("\nSetup incomplete. Please address the issues above.")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

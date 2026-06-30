"""
Proposal-document downloader.

Pulls raw proposal files (PDF/PPT/Word) from the shared Google Drive folder via
gdown. Parsing/embedding is handled directly by src/loaders/proposal_loader.py —
this module only fetches the source files.
"""

import logging
from pathlib import Path
from typing import Optional
import gdown

from config import RAW_PROPOSALS_DIR, EXTRACTED_PROPOSALS_DIR, GOOGLE_DRIVE_FOLDER_ID

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """Download proposal documents from Google Drive."""

    def __init__(self, raw_dir: Path = RAW_PROPOSALS_DIR, output_dir: Path = EXTRACTED_PROPOSALS_DIR):
        self.raw_dir = Path(raw_dir)
        self.output_dir = Path(output_dir)

    def _setup_cookies(self):
        """
        Copy gdrive_cookies.txt from project root to ~/.cache/gdown/cookies.txt
        so gdown can authenticate as the logged-in user.
        """
        import shutil
        from config import PROJECT_ROOT
        cookies_src = PROJECT_ROOT / "gdrive_cookies.txt"
        cookies_dst = Path.home() / ".cache" / "gdown" / "cookies.txt"
        if cookies_src.exists():
            cookies_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cookies_src, cookies_dst)
            logger.info(f"Cookies loaded from {cookies_src}")
            return True
        logger.warning("gdrive_cookies.txt not found — trying without auth (may fail for private folders)")
        return False

    def download_from_gdrive(self, folder_id: str = GOOGLE_DRIVE_FOLDER_ID, output_dir: Optional[Path] = None):
        """
        Download all files from Google Drive folder using gdown with cookie auth.
        Requires gdrive_cookies.txt in project root for private/shared folders.
        """
        if output_dir is None:
            output_dir = self.raw_dir

        output_dir.mkdir(parents=True, exist_ok=True)
        self._setup_cookies()

        try:
            logger.info(f"Downloading from Google Drive folder: {folder_id}")
            gdown.download_folder(
                url=f"https://drive.google.com/drive/folders/{folder_id}",
                output=str(output_dir),
                quiet=False,
                use_cookies=True
            )
            downloaded = list(output_dir.glob("*.*"))
            logger.info(f"Downloaded {len(downloaded)} files to {output_dir}")
        except Exception as e:
            logger.error(f"Error downloading from Google Drive: {e}")
            raise

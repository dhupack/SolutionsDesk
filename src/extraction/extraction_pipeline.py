"""
Extraction pipeline orchestrator for downloading and processing proposal documents.
"""

import logging
import json
from pathlib import Path
from typing import List, Dict, Optional
import gdown

from src.extraction.document_parser import DocumentParser
from src.extraction.section_identifier import SectionIdentifier
from src.extraction.markdown_converter import MarkdownConverter
from config import (
    RAW_PROPOSALS_DIR,
    EXTRACTED_PROPOSALS_DIR,
    EXTRACTION_METADATA_PATH,
    GOOGLE_DRIVE_FOLDER_ID
)

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """Orchestrate extraction of proposal documents."""

    def __init__(self, raw_dir: Path = RAW_PROPOSALS_DIR, output_dir: Path = EXTRACTED_PROPOSALS_DIR):
        self.raw_dir = Path(raw_dir)
        self.output_dir = Path(output_dir)
        self.metadata_list = []

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

    def process_file(self, file_path: str, client_name: str, document_name: str) -> Optional[Dict]:
        """
        Process a single proposal document.
        
        Args:
            file_path: Path to the document file
            client_name: Name of the client
            document_name: Name of the document
            
        Returns:
            Metadata dict or None if extraction failed
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.error(f"File does not exist: {file_path}")
            return None

        try:
            logger.info(f"Processing: {file_path}")
            
            # Step 1: Extract text from document
            full_text, content_info, file_type = DocumentParser.extract_from_file(str(file_path))
            
            # Step 2: Identify problems and solutions
            sections = SectionIdentifier.extract_best_sections(full_text)
            
            # Step 3: Convert to markdown
            markdown_content = MarkdownConverter.create_markdown_content(
                client_name=client_name,
                document_name=document_name,
                sections=sections,
                original_file_format=file_type,
                original_file_path=str(file_path)
            )
            
            # Step 4: Save markdown file
            md_file_path = MarkdownConverter.save_markdown_file(
                self.output_dir,
                client_name,
                document_name,
                markdown_content
            )
            
            # Step 5: Create and save metadata
            metadata = MarkdownConverter.create_metadata(
                file_path=md_file_path,
                client_name=client_name,
                document_name=document_name,
                original_file_format=file_type,
                original_file_path=str(file_path),
                extracted_sections=sections,
                extraction_status="success"
            )
            
            self.metadata_list.append(metadata)
            logger.info(f"Successfully processed: {file_path}")
            return metadata
            
        except Exception as e:
            logger.error(f"Error processing {file_path}: {str(e)}")
            metadata = MarkdownConverter.create_metadata(
                file_path="",
                client_name=client_name,
                document_name=document_name,
                original_file_format="",
                original_file_path=str(file_path),
                extracted_sections={},
                extraction_status=f"failed: {str(e)}"
            )
            self.metadata_list.append(metadata)
            return None

    def process_batch(self, file_configs: List[Dict]) -> Dict:
        """
        Process a batch of files.
        
        Args:
            file_configs: List of dicts with keys: file_path, client_name, document_name
            
        Returns:
            Summary dict with success/failure counts
        """
        success_count = 0
        failure_count = 0

        for config in file_configs:
            result = self.process_file(
                file_path=config['file_path'],
                client_name=config['client_name'],
                document_name=config['document_name']
            )
            if result:
                success_count += 1
            else:
                failure_count += 1

        return {
            "total": len(file_configs),
            "success": success_count,
            "failure": failure_count,
            "metadata_file": self._save_metadata()
        }

    def _save_metadata(self) -> Path:
        """
        Save extraction metadata to JSON file.
        """
        EXTRACTION_METADATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(EXTRACTION_METADATA_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.metadata_list, f, indent=2)
            logger.info(f"Saved extraction metadata to {EXTRACTION_METADATA_PATH}")
            return EXTRACTION_METADATA_PATH
        except Exception as e:
            logger.error(f"Error saving metadata: {str(e)}")
            raise

    def get_extracted_files(self) -> List[Path]:
        """
        Get list of all extracted markdown files.
        """
        if not self.output_dir.exists():
            return []
        return list(self.output_dir.glob("*.md"))

    def get_metadata(self) -> List[Dict]:
        """
        Get extraction metadata for all processed files.
        """
        return self.metadata_list

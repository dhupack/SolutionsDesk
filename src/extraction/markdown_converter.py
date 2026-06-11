"""
Markdown converter module for converting extracted sections to markdown format.
"""

import logging
from pathlib import Path
from typing import Dict, List
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class MarkdownConverter:
    """Convert extracted document sections to markdown format with metadata."""

    @staticmethod
    def create_markdown_content(
        client_name: str,
        document_name: str,
        sections: Dict,
        original_file_format: str,
        original_file_path: str
    ) -> str:
        """
        Create markdown content from extracted sections.
        
        Args:
            client_name: Name of the client/proposal
            document_name: Name of the document
            sections: Dict with 'problems' and 'solutions' lists
            original_file_format: Original format (pdf, ppt, word)
            original_file_path: Path to original file
            
        Returns:
            Markdown formatted string
        """
        markdown = f"""# {client_name} - {document_name}

**Source:** {original_file_format.upper()}  
**Original File:** {original_file_path}  
**Extracted:** {datetime.now().isoformat()}

---

## Problems & Challenges

"""
        # Add problem sections
        if sections.get('problems'):
            for idx, problem in enumerate(sections['problems'], 1):
                markdown += f"### Problem {idx}\n\n"
                markdown += f"**Confidence:** {problem.get('confidence', 0):.2%}\n\n"
                markdown += f"**Keywords Matched:** {', '.join(problem.get('matched_keywords', []))}\n\n"
                markdown += f"{problem.get('content', '')}\n\n"
                markdown += "---\n\n"
        else:
            markdown += "No problems identified.\n\n---\n\n"

        markdown += """## Solutions & Technical Approach

"""
        # Add solution sections
        if sections.get('solutions'):
            for idx, solution in enumerate(sections['solutions'], 1):
                markdown += f"### Solution {idx}\n\n"
                markdown += f"**Confidence:** {solution.get('confidence', 0):.2%}\n\n"
                markdown += f"**Keywords Matched:** {', '.join(solution.get('matched_keywords', []))}\n\n"
                markdown += f"{solution.get('content', '')}\n\n"
                markdown += "---\n\n"
        else:
            markdown += "No solutions identified.\n\n---\n\n"

        return markdown

    @staticmethod
    def save_markdown_file(
        output_dir: Path,
        client_name: str,
        document_name: str,
        markdown_content: str
    ) -> Path:
        """
        Save markdown content to file.
        
        Returns:
            Path to saved file
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Create filename from client and document names
        safe_client = client_name.replace(" ", "_").replace("/", "_")
        safe_doc = document_name.replace(" ", "_").replace("/", "_")
        filename = f"{safe_client}_{safe_doc}.md"
        
        file_path = output_dir / filename
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            logger.info(f"Saved markdown file: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Error saving markdown file {file_path}: {str(e)}")
            raise

    @staticmethod
    def create_metadata(
        file_path: str,
        client_name: str,
        document_name: str,
        original_file_format: str,
        original_file_path: str,
        extracted_sections: Dict,
        extraction_status: str = "success"
    ) -> Dict:
        """
        Create metadata dictionary for the extraction.
        
        Returns:
            Metadata dict
        """
        return {
            "markdown_file": str(file_path),
            "client_name": client_name,
            "document_name": document_name,
            "original_file_format": original_file_format,
            "original_file_path": str(original_file_path),
            "extraction_timestamp": datetime.now().isoformat(),
            "extraction_status": extraction_status,
            "problems_count": len(extracted_sections.get('problems', [])),
            "solutions_count": len(extracted_sections.get('solutions', [])),
            "average_problem_confidence": (
                sum(p.get('confidence', 0) for p in extracted_sections.get('problems', [])) / 
                len(extracted_sections.get('problems', [])) 
                if extracted_sections.get('problems') else 0
            ),
            "average_solution_confidence": (
                sum(s.get('confidence', 0) for s in extracted_sections.get('solutions', [])) / 
                len(extracted_sections.get('solutions', [])) 
                if extracted_sections.get('solutions') else 0
            )
        }

    @staticmethod
    def save_metadata_batch(output_dir: Path, metadata_list: List[Dict], batch_id: str):
        """
        Save extraction metadata for a batch of files.
        """
        output_dir = Path(output_dir)
        metadata_file = output_dir / f"extraction_metadata_{batch_id}.json"
        
        try:
            with open(metadata_file, 'w', encoding='utf-8') as f:
                json.dump(metadata_list, f, indent=2)
            logger.info(f"Saved metadata for {len(metadata_list)} files to {metadata_file}")
        except Exception as e:
            logger.error(f"Error saving metadata: {str(e)}")
            raise

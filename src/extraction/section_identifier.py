"""
Section identifier module for detecting Problem and Solution sections in documents.
"""

import re
import logging
from typing import List, Dict, Tuple, Optional
from config import PROBLEM_KEYWORDS, SOLUTION_KEYWORDS

logger = logging.getLogger(__name__)


class SectionIdentifier:
    """Identify Problem and Solution sections in extracted document text."""

    @staticmethod
    def find_section_boundaries(text: str, keywords: List[str]) -> List[Tuple[int, int, str]]:
        """
        Find sections containing specific keywords.
        
        Args:
            text: Full document text
            keywords: List of keywords to search for
            
        Returns:
            List of (start_char_pos, end_char_pos, matched_keyword)
        """
        lines = text.split('\n')
        sections = []
        
        for line_num, line in enumerate(lines):
            line_lower = line.lower()
            for keyword in keywords:
                if keyword in line_lower:
                    # Calculate character position
                    start_pos = sum(len(l) + 1 for l in lines[:line_num])
                    sections.append({
                        "line_num": line_num,
                        "char_pos": start_pos,
                        "keyword": keyword,
                        "line_text": line.strip()
                    })
        
        return sections

    @staticmethod
    def extract_section_content(text: str, start_line: int, end_line: Optional[int] = None, max_lines: int = 50) -> str:
        """
        Extract content from start_line to end_line (or next max_lines if end_line not provided).
        """
        lines = text.split('\n')
        
        if end_line is None:
            end_line = min(start_line + max_lines, len(lines))
        
        content = '\n'.join(lines[start_line:end_line])
        return content.strip()

    @staticmethod
    def identify_problems(text: str) -> List[Dict]:
        """
        Identify Problem sections in document.
        
        Returns:
            List of dicts: {"start_line": int, "end_line": int, "content": str, "confidence": float}
        """
        lines = text.split('\n')
        problems = []
        
        for line_num, line in enumerate(lines):
            line_lower = line.lower()
            # Check if line contains problem-related keywords
            keyword_matches = [kw for kw in PROBLEM_KEYWORDS if kw in line_lower]
            
            if keyword_matches:
                # Extract content around this line
                start_line = max(0, line_num - 2)  # Include 2 lines before
                end_line = min(len(lines), line_num + 30)  # Include next 30 lines
                
                content = SectionIdentifier.extract_section_content(text, start_line, end_line)
                
                # Calculate confidence based on number of matching keywords
                confidence = min(len(keyword_matches) * 0.3, 1.0)
                
                problems.append({
                    "start_line": start_line,
                    "end_line": end_line,
                    "content": content,
                    "matched_keywords": keyword_matches,
                    "confidence": confidence
                })
        
        logger.info(f"Identified {len(problems)} potential Problem sections")
        return problems

    @staticmethod
    def identify_solutions(text: str) -> List[Dict]:
        """
        Identify Solution sections in document.
        
        Returns:
            List of dicts: {"start_line": int, "end_line": int, "content": str, "confidence": float}
        """
        lines = text.split('\n')
        solutions = []
        
        for line_num, line in enumerate(lines):
            line_lower = line.lower()
            # Check if line contains solution-related keywords
            keyword_matches = [kw for kw in SOLUTION_KEYWORDS if kw in line_lower]
            
            if keyword_matches:
                # Extract content around this line
                start_line = max(0, line_num - 2)  # Include 2 lines before
                end_line = min(len(lines), line_num + 35)  # Include next 35 lines
                
                content = SectionIdentifier.extract_section_content(text, start_line, end_line)
                
                # Calculate confidence based on number of matching keywords
                confidence = min(len(keyword_matches) * 0.3, 1.0)
                
                solutions.append({
                    "start_line": start_line,
                    "end_line": end_line,
                    "content": content,
                    "matched_keywords": keyword_matches,
                    "confidence": confidence
                })
        
        logger.info(f"Identified {len(solutions)} potential Solution sections")
        return solutions

    @staticmethod
    def extract_best_sections(text: str) -> Dict:
        """
        Extract best Problem and Solution sections from document.
        
        Returns:
            {
                "problems": [{"content": str, "confidence": float, ...}],
                "solutions": [{"content": str, "confidence": float, ...}]
            }
        """
        problems = SectionIdentifier.identify_problems(text)
        solutions = SectionIdentifier.identify_solutions(text)
        
        # Sort by confidence and remove duplicates
        problems = sorted(problems, key=lambda x: x['confidence'], reverse=True)
        solutions = sorted(solutions, key=lambda x: x['confidence'], reverse=True)
        
        # Remove overlapping sections (keep highest confidence)
        unique_problems = []
        for problem in problems:
            if not any(p['start_line'] == problem['start_line'] for p in unique_problems):
                unique_problems.append(problem)
        
        unique_solutions = []
        for solution in solutions:
            if not any(s['start_line'] == solution['start_line'] for s in unique_solutions):
                unique_solutions.append(solution)
        
        return {
            "problems": unique_problems[:3],  # Keep top 3
            "solutions": unique_solutions[:3]  # Keep top 3
        }

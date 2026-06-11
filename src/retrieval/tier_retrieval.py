import logging
from typing import Dict, Optional, List
from src.loaders.feature_loader import FeatureLoader
from src.loaders.proposal_loader import ProposalLoader
from config import SIMILARITY_THRESHOLD, TIER2_SIMILARITY_THRESHOLD, TOP_K_RESULTS

logger = logging.getLogger(__name__)


class TierRetrieval:

    def __init__(self):
        self.feature_loader = FeatureLoader()
        self.proposal_loader = ProposalLoader()
        self.feature_loader_initialized = False
        self.proposal_loader_initialized = False

    def initialize_feature_index(self) -> bool:
        try:
            self.feature_loader.load_index()
            if self.feature_loader.faiss_index and self.feature_loader.metadata:
                self.feature_loader_initialized = True
                return True
        except Exception as e:
            logger.error(f"Error loading feature index: {e}")
        return False

    def initialize_proposal_index(self) -> bool:
        try:
            self.proposal_loader.load_index()
            if self.proposal_loader.faiss_index and self.proposal_loader.metadata:
                self.proposal_loader_initialized = True
                return True
        except Exception as e:
            logger.error(f"Error loading proposal index: {e}")
        return False

    @staticmethod
    def _keyword_boost(query: str, feature_name: str, full_row: dict) -> float:
        query_lower = query.lower()
        name_lower = feature_name.lower()
        desc_lower = " ".join(str(v) for v in (full_row or {}).values()).lower()

        # Strong terms: 0.20 when in feature NAME, 0.06 when only in description
        strong_terms = [
            'gps', 'sim', 'toll', 'rfid', 'adas', 'tms', 'ulip', 'poi', 'ocr',
            'weighbridge', 'eway', 'challan', 'fastag', 'deviat', 'geofenc',
            'vahan', 'sarathi', 'inbound', 'outbound', 'dms', 'anpr', 'sla',
            'eta', 'pod', 'yard', 'dock', 'iot', 'bot', 'api', 'e-seal',
            'detain', 'detention', 'delay', 'reverse logistics', 'parking',
            'blacklist', 'whitelist', 'route deviation', 'off route',
        ]

        # Weak terms: appear as context in queries ("at the gate", "check RC")
        # Only get description-level boost (0.06) even if in feature name
        weak_terms = [
            'gate', 'rc', 'fitness', 'insurance', 'permit', 'compliance',
        ]

        boost = 0.0
        for term in strong_terms:
            if term in query_lower:
                if term in name_lower:
                    boost += 0.20
                elif term in desc_lower:
                    boost += 0.06

        for term in weak_terms:
            if term in query_lower:
                if term in name_lower or term in desc_lower:
                    boost += 0.06  # flat description-level boost regardless of position

        return min(boost, 0.30)

    def query_tier1_features(self, query: str) -> Optional[Dict]:
        if not self.feature_loader_initialized:
            return None

        # Get more candidates, then rerank with hybrid score
        results = self.feature_loader.search(query, k=8)
        if not results:
            return None

        # Compute hybrid score = semantic + keyword boost
        for r in results:
            name = r['metadata'].get('feature_name', '')
            row  = r['metadata'].get('full_row', {})
            r['hybrid_score'] = r['similarity_score'] + self._keyword_boost(query, name, row)

        results.sort(key=lambda x: x['hybrid_score'], reverse=True)
        logger.info("Tier 1 hybrid scores: " +
                    ", ".join(f"{r['metadata'].get('feature_name','?')}={r['hybrid_score']:.3f}"
                              for r in results[:4]))

        best = results[0]
        if best['hybrid_score'] > SIMILARITY_THRESHOLD:
            logger.info(f"Tier 1 hit — {best['metadata'].get('feature_name')} (hybrid={best['hybrid_score']:.3f})")
            return {
                "tier": 1,
                "similarity_score": best['hybrid_score'],
                "feature_id": best['metadata'].get('feature_id'),
                "feature_name": best['metadata'].get('feature_name'),
                "row_number": best['metadata'].get('row_number'),
                "content": best['metadata'].get('full_row'),
                "all_results": results
            }
        return None

    def query_tier2_proposals(self, query: str) -> Optional[Dict]:
        if not self.proposal_loader_initialized:
            return None
        results = self.proposal_loader.search(query, k=TOP_K_RESULTS)
        if results and results[0]['similarity_score'] > TIER2_SIMILARITY_THRESHOLD:
            best = results[0]
            logger.info(f"Tier 2 hit — similarity: {best['similarity_score']:.3f}")
            return {
                "tier": 2,
                "similarity_score": best['similarity_score'],
                "client_name": best['metadata'].get('client_name'),
                "filename": best['metadata'].get('filename'),
                "section_type": best['metadata'].get('section_type'),
                "source_file": best['metadata'].get('source_file'),
                "industry": best['metadata'].get('industry', ''),
                "document_type": best['metadata'].get('document_type', ''),
                "chunk_index": best['metadata'].get('chunk_index', 0),
                "word_count": best['metadata'].get('word_count', 0),
                "content": best['metadata'].get('content', ''),
                "all_results": results
            }
        return None

    def get_all_features_compact(self) -> str:
        """All 122 features as compact text for LLM pitch prompt."""
        if not self.feature_loader.metadata:
            return ""
        cpl_lines, xswift_lines = [], []
        for item in self.feature_loader.metadata:
            row = item.get('full_row', {})
            name = item.get('feature_name', '')
            fid = item.get('feature_id', '')
            bucket = str(row.get('Bucket', ''))
            module = str(row.get('Module / Area', ''))
            what = str(row.get('What it does', ''))[:100]
            value = str(row.get('Business Value / Impact', ''))[:80]
            line = f"  #{fid} {name} [{module}] — {what} | Value: {value}"
            if any(b in bucket for b in ['CPL', 'CPoL', 'Platform']):
                cpl_lines.append(line)
            else:
                xswift_lines.append(line)
        out = "=== CPL / CPoL Features (Plant & Port Logistics) ===\n"
        out += "\n".join(cpl_lines)
        out += "\n\n=== XSWIFT Features (Fleet & Long-haul Transport) ===\n"
        out += "\n".join(xswift_lines)
        return out

    def get_context_for_llm(self, query: str) -> str:
        context = ""
        if self.feature_loader_initialized:
            feature_results = self.feature_loader.search(query, k=2)
            if feature_results:
                context += "## Related Features\n"
                for r in feature_results:
                    row = r['metadata'].get('full_row', {})
                    name = r['metadata'].get('feature_name', 'Unknown')
                    what = row.get('What it does', '') if isinstance(row, dict) else ''
                    context += f"- **{name}**: {what}\n"
                context += "\n"

        if self.proposal_loader_initialized:
            proposal_results = self.proposal_loader.search(query, k=2)
            if proposal_results:
                context += "## Related Proposals\n"
                for r in proposal_results:
                    client = r['metadata'].get('client_name', 'Unknown')
                    section = r['metadata'].get('section_type', '')
                    content = r['metadata'].get('content', '')
                    context += f"- **{client}** ({section}):\n  {content[:300]}\n"
                context += "\n"

        return context

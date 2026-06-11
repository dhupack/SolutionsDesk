import os
import re
import logging
from typing import TypedDict
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.retrieval.tier_retrieval import TierRetrieval
from config import get_llm

logger = logging.getLogger(__name__)


class RAGState(TypedDict):
    query: str
    final_answer: str
    source_reference: str
    tier_level: int


# ── Score thresholds ───────────────────────────────────────────────────────────
# Tuned for OpenAI text-embedding-3-large (higher noise floor than local mpnet):
#   clear feature hits ~0.63+ · clear proposal hits ~0.60+ · unrelated noise ~0.34-0.48
_FEATURE_STRONG   = 0.55   # clear, direct feature match wins Tier 1
_PROPOSAL_STRONG  = 0.52   # genuine proposal match (non-impl query) → proposal tier
_PROPOSAL_PRESENT = 0.42   # below this the proposal is noise → ignore (lets Tier 3 trigger)

# ── Per-source JSON schemas ────────────────────────────────────────────────────
_SCHEMA_FEATURE = '''{
  "type": "pitch" | "factual",
  "opening": "1-2 sentence positioning for this customer problem",
  "solutions": [
    {"id": "#ID", "name": "Exact Feature Name", "product": "XSWIFT or CPL", "points": ["a complete phrase of about 6-12 words explaining what it does or why it fits — NOT a one or two word label", "another 6-12 word point", "optional third 6-12 word point"]}
  ],
  "past_implementations": [
    {"client": "Client Name", "industry": "industry", "summary": "What Axestrack deployed and key outcome"}
  ]
}'''

_SCHEMA_PROPOSAL = '''{
  "type": "pitch" | "factual",
  "opening": "1-2 sentence answer grounded in what Axestrack actually implemented",
  "proposal_findings": [
    {
      "client": "Client Name from proposal context above",
      "industry": "industry",
      "file": "exact filename from proposal context e.g. Proposal_Doc.pdf",
      "key_points": [
        {"text": "Specific thing deployed/designed for this client", "page": "the Page value shown for the chunk this came from, e.g. p.5 or slide 3, or empty string if none"},
        {"text": "Another specific detail", "page": "matching page ref or empty"}
      ]
    }
  ],
  "solutions": [
    {"id": "#ID", "name": "Exact Feature Name", "product": "XSWIFT or CPL", "points": ["a complete phrase of about 6-12 words on how it maps to what was deployed — NOT a one or two word label", "another 6-12 word point", "optional third 6-12 word point"]}
  ],
  "past_implementations": [
    {"client": "Client Name", "industry": "industry", "summary": "One-line summary"}
  ]
}'''

_SCHEMA_LLM = '''{
  "type": "pitch" | "factual",
  "opening": "1-2 sentence answer based on general knowledge",
  "opening_source": "Docs | Model Knowledge | Docs + Model Knowledge",
  "solutions": [
    {
      "id": null,
      "name": "Suggested Approach",
      "product": null,
      "points": ["a complete phrase of about 6-12 words on what this involves — NOT a one or two word label", "another 6-12 word point"],
      "source": "Docs | Model Knowledge | Docs + Model Knowledge"
    }
  ],
  "reasoning": "Honest explanation: what was missing from the feature catalog and proposals, and why general knowledge was used"
}

SOURCE LABEL RULES (for opening_source and each solution source field):
- "Docs"                   : the information comes directly from the retrieved features or proposal context above
- "Model Knowledge"        : the information comes from the LLM's own general knowledge, not from the docs
- "Docs + Model Knowledge" : combines a fact from the docs with additional explanation from the LLM'''


class RAGWorkflow:

    def __init__(self):
        self.llm = get_llm(temperature=0.2)
        self.tier_retrieval = TierRetrieval()
        self.graph = None
        self.saver = MemorySaver()

    def initialize_tier_retrieval(self) -> bool:
        feature_ok = self.tier_retrieval.initialize_feature_index()
        proposal_ok = self.tier_retrieval.initialize_proposal_index()
        return feature_ok or proposal_ok

    def _rewrite_query(self, query: str) -> str:
        """
        Rewrite the user's raw query into a clean, semantically rich version
        for better FAISS retrieval. Falls back to original on any error.
        """
        prompt = (
            "You are a query cleaner for a B2B logistics software assistant.\n"
            "The knowledge base is in ENGLISH, so the cleaned query MUST be in English.\n"
            "Clean the query below by ONLY:\n"
            "- Translating it to English if it is in any other language or script (e.g. Hindi, Hinglish/Romanized Hindi). Preserve the EXACT meaning and the SAME question type — translate, do not answer or reinterpret.\n"
            "- Fixing typos (e.g. 'wt did' → 'what did', '4' → 'for')\n"
            "- Expanding logistics abbreviations (e.g. DMS → Driver Monitoring System, ePOD → Electronic Proof of Delivery, RFID → Radio Frequency Identification)\n"
            "- Expanding product shorthand (e.g. 'dashcam thing' → 'dashcam and Driver Monitoring System for fleet safety')\n\n"
            "STRICT RULES — do NOT:\n"
            "- Change the type of question ('what is X?' must stay 'what is X?', never becomes 'which feature handles X?')\n"
            "- Add Axestrack product names or feature names unless they were in the original\n"
            "- Add context or information not present in the original\n"
            "- Rephrase or restructure the question\n\n"
            "If the query is already clear, return it unchanged.\n"
            "Return ONLY the cleaned query. No explanation, no quotes.\n\n"
            f"Query: {query}"
        )
        try:
            response = self.llm.invoke(prompt)
            rewritten = (response.content if hasattr(response, 'content') else str(response)).strip()
            # Safety: if rewrite is empty, too short, or suspiciously long, use original
            if 10 <= len(rewritten) <= 400:
                logger.info(f"Query rewrite: '{query}' → '{rewritten}'")
                return rewritten
        except Exception as e:
            logger.warning(f"Query rewrite failed: {e}")
        return query

    def _build_generation(self, original_query: str) -> dict:
        """Retrieve, route, and build the generation prompt — everything except the
        final LLM call. Shared by the blocking node and the streaming path."""
        # ── Step 1: Rewrite query for better retrieval ─────────────────────────
        retrieval_query = self._rewrite_query(original_query)

        # ── Step 2: FAISS retrieval using rewritten query ─────────────────────
        # Embed the query ONCE and reuse the vector for both indexes (both use the
        # same embedding model), instead of embedding it separately per loader.
        feat_init = self.tier_retrieval.feature_loader_initialized
        prop_init = self.tier_retrieval.proposal_loader_initialized

        query_vec = None
        if feat_init or prop_init:
            embedder = (self.tier_retrieval.feature_loader.embeddings if feat_init
                        else self.tier_retrieval.proposal_loader.embeddings)
            query_vec = embedder.embed_query(retrieval_query)

        feature_results = (self.tier_retrieval.feature_loader.search_vec(query_vec, k=15)
                           if feat_init else [])
        proposal_results = (self.tier_retrieval.proposal_loader.search_vec(query_vec, k=5)
                            if prop_init else [])

        # Build feature context
        feature_context = ""
        for r in feature_results:
            score  = r['similarity_score']
            row    = r['metadata'].get('full_row', {})
            name   = r['metadata'].get('feature_name', '')
            fid    = r['metadata'].get('feature_id', '')
            bucket = str(row.get('Bucket', ''))
            what   = str(row.get('What it does', ''))
            value  = str(row.get('Business Value / Impact', ''))
            deps   = str(row.get('Dependencies / Inputs', ''))
            sales  = str(row.get('Sales Talking Point', ''))
            module = str(row.get('Module / Area', ''))
            product = 'CPL' if any(b in bucket for b in ['CPL', 'CPoL', 'Platform']) else 'XSWIFT'
            label   = "HIGH" if score >= 0.55 else ("MEDIUM" if score >= 0.42 else "LOW")
            feature_context += (
                f"\n#{fid} {name} ({product}) [Relevance: {label} {score:.0%}]\n"
                f"  Module: {module} | Bucket: {bucket}\n"
                f"  What it does: {what}\n"
                f"  Business Value: {value}\n"
                f"  Sales Talking Point: {sales}\n"
                f"  Dependencies: {deps}\n"
            )

        # Build proposal context — richer content for proposal-source answers
        proposal_context = ""
        best_proposal_score = 0.0
        for r in proposal_results:
            score = r['similarity_score']
            if score > _PROPOSAL_PRESENT:
                if score > best_proposal_score:
                    best_proposal_score = score
                client   = r['metadata'].get('client_name', '')
                industry = r['metadata'].get('industry', '')
                filename = r['metadata'].get('filename', '')
                page_ref = r['metadata'].get('page_ref', '')
                content  = r['metadata'].get('content', '')[:600]
                page_part = f" | Page: {page_ref}" if page_ref else ""
                proposal_context += (
                    f"\n[Client: {client} | Industry: {industry} | Score: {score:.0%} | File: {filename}{page_part}]\n"
                    f"{content}\n"
                )

        # ── Determine source type programmatically ─────────────────────────────
        best_feature = feature_results[0] if feature_results else None
        best_score   = best_feature['similarity_score'] if best_feature else 0.0
        best_name    = best_feature['metadata'].get('feature_name', '') if best_feature else ''

        _IMPL_KEYWORDS = [
            'implement', 'deploy', 'what did', 'did axestrack', 'done for',
            'solution for', 'propose', 'proposal for', 'client', 'case study',
        ]
        combined      = (original_query + ' ' + retrieval_query).lower()
        is_impl_query = any(kw in combined for kw in _IMPL_KEYWORDS)

        if best_score >= _FEATURE_STRONG and not is_impl_query:
            source_type = "feature_catalog"
            tier = 1
        elif best_proposal_score >= _PROPOSAL_STRONG or (is_impl_query and best_proposal_score >= _PROPOSAL_PRESENT):
            source_type = "proposal"
            tier = 2
        elif proposal_context:
            source_type = "feature_catalog"
            tier = 2
        else:
            source_type = "llm_knowledge"
            tier = 3

        if os.getenv("DEBUG_RETRIEVAL"):
            print(f"[retrieval] feature_best={best_score:.3f} "
                  f"proposal_best={best_proposal_score:.3f} impl={is_impl_query} "
                  f"-> tier {tier} ({source_type})  q='{retrieval_query[:60]}'")

        proposal_section = (
            "--- RELEVANT PAST PROPOSALS ---\n" + proposal_context
        ) if proposal_context else ""

        if source_type == "feature_catalog":
            source_instruction = (
                "The top matched features above answer this query. Answer from those features only.\n"
                "If past proposals are provided, populate past_implementations with 1-3 relevant ones.\n\n"
                "Use this JSON schema:\n" + _SCHEMA_FEATURE
            )
        elif source_type == "proposal":
            source_instruction = (
                "The past proposals contain more specific information than the features for this query.\n"
                "Answer primarily from the proposal content above. Extract specific details into proposal_findings.\n"
                "Still include relevant catalog features in solutions where they map to what was done.\n\n"
                "Use this JSON schema:\n" + _SCHEMA_PROPOSAL
            )
        else:
            source_instruction = (
                "Neither the matched features nor past proposals have a good answer for this query.\n"
                "Answer from general industry knowledge. Be honest — explain in 'reasoning' why.\n\n"
                "Use this JSON schema:\n" + _SCHEMA_LLM
            )

        # Show rewritten query only if it differs meaningfully from original
        query_section = f"User Query: {original_query}\n"
        if retrieval_query.lower().strip() != original_query.lower().strip():
            query_section += f"Interpreted as: {retrieval_query}\n"

        prompt = (
            "You are an Axestrack product expert helping a new solutions team member. Accuracy is critical.\n\n"
            f"{query_section}\n"
            "--- TOP SEMANTICALLY MATCHED FEATURES (use exact Feature IDs and names from here) ---\n"
            f"{feature_context if feature_context else 'None retrieved.'}\n\n"
            f"{proposal_section}\n\n"
            "STRICT RULES:\n"
            "1. Use exact feature names and IDs (#ID) exactly as shown above. Never invent features.\n"
            "2. For proposal source: extract SPECIFIC details from proposal text above.\n"
            "3. Only include features genuinely relevant to the query. Do not pad.\n\n"
            "OUTPUT: Respond with ONLY valid JSON. No markdown fences, no text outside the JSON.\n\n"
            f"{source_instruction}"
        )

        source = (
            f"[Feature Catalogue - Best match: {best_name} ({best_score:.0%})]"
            if best_feature else "[LLM General Knowledge]"
        )

        logger.info(f"Tier={tier} source={source_type} | orig='{original_query}' | rewritten='{retrieval_query}'")

        return {"prompt": prompt, "source_type": source_type, "source": source, "tier": tier}

    def _generate_response(self, state: RAGState) -> dict:
        gen = self._build_generation(state["query"])
        response = self.llm.invoke(gen["prompt"])
        answer = response.content if hasattr(response, 'content') else str(response)
        # Inject source_type into the answer reference so the renderer knows the path
        return {
            "final_answer": answer,
            "source_reference": f"{gen['source_type']}|{gen['source']}",
            "tier_level": gen["tier"],
        }

    def stream_generate(self, query: str):
        """Generator for streaming responses: yields one 'meta' event, then many
        'delta' text chunks as the LLM produces them, then a final 'done' event."""
        gen = self._build_generation(query)
        yield {"type": "meta", "source_type": gen["source_type"],
               "source": gen["source"], "tier": gen["tier"]}
        parts = []
        try:
            for chunk in self.llm.stream(gen["prompt"]):
                text = chunk.content if hasattr(chunk, "content") else str(chunk)
                if text:
                    parts.append(text)
                    yield {"type": "delta", "text": text}
        except Exception as e:
            logger.warning(f"Streaming failed, falling back to full invoke: {e}")
            if not parts:
                response = self.llm.invoke(gen["prompt"])
                full = response.content if hasattr(response, 'content') else str(response)
                parts.append(full)
                yield {"type": "delta", "text": full}
        yield {"type": "done", "answer": "".join(parts)}

    def build_graph(self):
        workflow = StateGraph(RAGState)
        workflow.add_node("generate_response", self._generate_response)
        workflow.set_entry_point("generate_response")
        workflow.add_edge("generate_response", END)
        self.graph = workflow.compile(checkpointer=self.saver)
        return self.graph

    def invoke(self, query: str, session_id: str = "default") -> dict:
        if not self.graph:
            self.build_graph()

        initial_state = {
            "query": query,
            "final_answer": "",
            "source_reference": "",
            "tier_level": 0,
        }

        config = {"configurable": {"thread_id": session_id}}
        try:
            result = self.graph.invoke(initial_state, config=config)
            src_raw = result.get("source_reference", "")
            # source_reference format: "source_type|display_source"
            if "|" in src_raw:
                source_type, display_source = src_raw.split("|", 1)
            else:
                source_type, display_source = "feature_catalog", src_raw
            return {
                "success": True,
                "query": query,  # original user query
                "answer": result.get("final_answer", ""),
                "source": display_source,
                "source_type": source_type,
                "tier_resolved": result.get("tier_level", 0),
            }
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            return {
                "success": False,
                "query": query,
                "answer": f"Error: {e}",
                "source": "None",
                "source_type": "feature_catalog",
                "tier_resolved": 0,
            }

    def clear_conversation(self, session_id: str = "default"):
        pass

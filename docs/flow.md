# Soldesk Chatbot — Complete Flow

End-to-end flow of the application: startup/initialization, the full `/api/chat`
RAG pipeline with every decision branch, and all auxiliary endpoints.

Source of truth: [`app_new.py`](../app_new.py) and
[`src/rag/langgraph_workflow.py`](../src/rag/langgraph_workflow.py).

```mermaid
flowchart TD
    %% ================= STARTUP =================
    subgraph BOOT["① App startup (app_new.py import)"]
        direction TB
        B1["load_dotenv() → read GROQ_API_KEY"] --> B2["RAGWorkflow()<br/>init ChatGroq + TierRetrieval + MemorySaver"]
        B2 --> B3["initialize_tier_retrieval()<br/>load FAISS indices"]
        B3 --> B3a{"feature index loads?"}
        B3 --> B3b{"proposal index loads?"}
        B3a -->|ok| FOK["feature_loader_initialized = True"]
        B3a -->|fail| FNO["feature search skipped"]
        B3b -->|ok| POK["proposal_loader_initialized = True"]
        B3b -->|fail| PNO["proposal search skipped"]
        FOK --> B4
        FNO --> B4
        POK --> B4
        PNO --> B4
        B4{"feature OR proposal ready?"}
        B4 -->|yes| RDY["_rag_ready = True"]
        B4 -->|"neither"| NRDY["_rag_ready = False (degraded)"]
        RDY --> B5["build_graph() → compile LangGraph"]
        NRDY --> B5
    end

    B5 --> Listen(["Flask serving on :5001"])

    %% ================= CHAT PIPELINE =================
    Listen --> Start(["User asks question in web UI"])
    Start --> Chat["POST /api/chat<br/>IN: messages[] JSON"]

    Chat --> RL{"Rate limit<br/>30/hour per IP?"}
    RL -->|exceeded| R429["OUT 429 Too Many Requests"]
    RL -->|ok| V1{"messages empty?"}
    V1 -->|yes| E1["OUT 400 'No messages provided'"]
    V1 -->|no| V2{"last user msg has text?"}
    V2 -->|no| E2["OUT 400 'No user query found'"]
    V2 -->|yes| Invoke["rag.invoke(query, session_id='default')"]

    %% --- Step 1: rewrite ---
    Invoke --> RW["Step 1 — Query rewrite (LLM call #1)<br/>IN: raw query (any lang / typos / abbrev)<br/>OUT: cleaned English query"]
    RW --> RWcase{"rewrite valid?<br/>10–400 chars & no error"}
    RWcase -->|yes| QGood["use rewritten query"]
    RWcase -->|"empty / too long / exception"| QOrig["fallback: original query"]

    %% --- Step 2: retrieval ---
    QGood --> Faiss
    QOrig --> Faiss
    Faiss["Step 2 — FAISS search (local embeddings)<br/>feature hits k=15 · proposal hits k=5"]
    Faiss --> FC{"feature index<br/>available?"}
    FC -->|yes| FCtx["build feature_context (all hits, HIGH/MED/LOW labels)"]
    FC -->|no| FCtx0["feature_context = empty"]
    FCtx --> PC{"proposal index<br/>available?"}
    FCtx0 --> PC
    PC -->|yes| PCtx["build proposal_context<br/>(only hits with score > 0.35)"]
    PC -->|no| PCtx0["proposal_context = empty"]

    %% --- Step 3: tier decision ---
    PCtx --> IMPL{"impl-keyword in query?<br/>(implement/deploy/client/proposal…)"}
    PCtx0 --> IMPL
    IMPL --> Decide{"Source & Tier decision<br/>(scores + impl flag)"}

    Decide -->|"feature ≥ 0.55<br/>AND not impl query"| T1["TIER 1 → feature_catalog<br/>SCHEMA_FEATURE · badge GREEN"]
    Decide -->|"proposal ≥ 0.45<br/>OR (impl & proposal ≥ 0.35)"| T2["TIER 2 → proposal<br/>SCHEMA_PROPOSAL · badge BLUE"]
    Decide -->|"proposal present<br/>but weak (≤0.45)"| T2b["TIER 2 → feature_catalog<br/>(proposals supplement) · badge GREEN"]
    Decide -->|"no feature & no proposal"| T3["TIER 3 → llm_knowledge<br/>SCHEMA_LLM · badge AMBER"]

    %% --- Step 4: generate ---
    T1 --> Gen
    T2 --> Gen
    T2b --> Gen
    T3 --> Gen
    Gen["Step 3 — Build prompt with chosen schema<br/>→ LLM call #2 generates answer<br/>OUT: JSON answer string"]

    %% --- Step 5: parse ---
    Gen --> Parse{"answer parses as JSON?"}
    Parse -->|yes| JBlocks["_json_to_blocks()<br/>solutions / proposal_findings /<br/>past_implementations / reasoning"]
    Parse -->|"no (plain text)"| TBlocks["_text_to_blocks()<br/>markdown→blocks fallback"]

    JBlocks --> Color["color citations + attach source links<br/>green=feature · blue=proposal · amber=LLM"]
    TBlocks --> Color
    Color --> Resp["OUT 200 JSON {badge, blocks}<br/>rendered as chat cards"]

    Invoke -.->|"any exception<br/>(result.success=False)"| Err500["OUT 500 {error}"]

    %% ================= AUX ENDPOINTS =================
    subgraph AUX["② Other endpoints"]
        direction TB
        FB["POST /api/feedback<br/>IN rating up/down + remark → append feedback.jsonl<br/>OUT ok / 500"]
        CF["GET /api/catalog-file/&lt;product&gt;<br/>match XSWIFT|CPL .xlsx → file / 404"]
        PF["GET /api/proposal-file/&lt;name&gt;<br/>traversal-safe lookup → file / 404"]
        RC["POST /api/reload-catalog<br/>IN X-Reload-Token<br/>valid → rebuild indices · invalid/missing → 401"]
        OMs["POST /api/online-mode/start<br/>kill orphans → launch PyQt caption window<br/>OUT started+pid / 404 if script missing"]
        OMx["POST /api/online-mode/stop<br/>OUT stopped / not_running"]
        HC["GET /health<br/>OUT rag_ready + index status"]
    end

    Listen --> AUX
```

## Notes

- **3-tier RAG cascade.** Every query passes through a single LangGraph node
  (`generate_response`); the "tiers" are score-threshold branches inside that
  node. Thresholds: feature `≥ 0.55`, proposal strong `≥ 0.45`, proposal present
  `≥ 0.35`.
- **Two LLM calls per request** — one to rewrite/translate the query, one to
  generate the answer. Both currently go to **Groq** (`ChatGroq`,
  `llama-3.3-70b-versatile`). These are the swap points for an OpenAI migration.
- **Startup degradation.** The app boots and serves even if one index fails to
  load; it is fully degraded (`_rag_ready = False`) only if both feature and
  proposal indices fail.
- **Local embeddings.** Retrieval uses `all-mpnet-base-v2` via
  sentence-transformers — no API key needed; only the two LLM calls require one.
- **impl-keyword override.** Words like *implement, deploy, client, proposal* can
  override a strong feature match and route the query into the proposal tier.

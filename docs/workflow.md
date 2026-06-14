# SolutionsDesk Chatbot — Complete Workflow

A single end-to-end view of the RAG chatbot for a non-code audience:

- **Phase A — Indexing SOP** (offline): how source documents become searchable vectors (chunking strategy, embeddings, FAISS).
- **Phase B — Query Workflow** (live): how a question becomes an answer (rewrite → parallel retrieval → similarity scoring → routing → generation → render).
- **Delivery modes**: Web Chat and Online (Google Meet) mode.

> Embeddings: OpenAI `text-embedding-3-large` (3072-dim) · LLM: OpenAI `gpt-4o-mini` (configurable) · Vector store: FAISS (cosine similarity).

---

## 1. Phase A — Indexing SOP (offline, run when content changes)

```mermaid
flowchart TD
    classDef io fill:#eef2ff,stroke:#6366f1,color:#1e1b4b;
    classDef proc fill:#ffffff,stroke:#475569,color:#0f172a;
    classDef case fill:#fffbeb,stroke:#f59e0b,color:#92400e;
    classDef out fill:#ecfdf5,stroke:#10b981,color:#065f46;

    %% ---------- Feature catalog ----------
    subgraph FEAT["A1 — Feature Catalog index"]
        direction TB
        FA["IN: data/feature_sheet/*.xlsx<br/>sheet = 'Feature catalogue'"]:::io
        FA --> FB["Read each row (pandas)<br/>1 row = 1 feature"]:::proc
        FB --> FC["Build text per feature:<br/>name x2 + Module + Bucket +<br/>What it does + Business Value +<br/>Sales Talking Point + Dependencies"]:::proc
        FC --> FD["Embed → text-embedding-3-large<br/>(3072-dim vector)"]:::proc
        FD --> FE["normalize_L2 → FAISS IndexFlatIP<br/>(inner product = cosine)"]:::proc
        FE --> FF["OUT: feature_index.faiss +<br/>feature_metadata.json<br/>(feature_id, name, full_row)"]:::out
    end

    %% ---------- Proposals ----------
    subgraph PROP["A2 — Proposal index (chunking strategy)"]
        direction TB
        PA["IN: data/raw_proposals/&lt;client&gt;/*<br/>folder name = client name"]:::io
        PA --> PT{"File type?"}:::case
        PT -->|PDF| P_PDF["Extract per page → split on blank lines<br/>CASE: keep paragraphs > 60 chars<br/>CASE: drop boilerplate (TOC / footer / page #)<br/>page ref = 'p.N'"]:::case
        PT -->|PPT / PPTX| P_PPT["One chunk per slide<br/>CASE: keep if > 60 chars & not boilerplate<br/>page ref = 'slide N'"]:::case
        PT -->|DOC / DOCX| P_DOC["Split by heading sections → paragraphs > 60 chars<br/>page ref = '' (Word has no reliable pages)"]:::case

        P_PDF --> PCHUNK
        P_DOC --> PCHUNK
        PCHUNK["Chunk: ~300 words/chunk,<br/>overlap = 1 paragraph<br/>CASE: discard chunk if < 100 chars"]:::case
        P_PPT --> PIND
        PCHUNK --> PIND

        PIND["Detect industry:<br/>1) client-name map → 2) content keywords<br/>→ else 'logistics'"]:::proc
        PIND --> PEMB["embed_text = 'Client | Industry | File:' + chunk<br/>→ embed (3072-dim) → normalize_L2 → IndexFlatIP"]:::proc
        PEMB --> POUT["OUT: proposal_index.faiss +<br/>proposal_metadata.json<br/>(client, file, industry, page_ref,<br/>chunk_index, word_count, content)"]:::out
    end
```

---

## 2. Phase B — Live Query Workflow (per question)

```mermaid
flowchart TD
    classDef io fill:#eef2ff,stroke:#6366f1,color:#1e1b4b;
    classDef proc fill:#ffffff,stroke:#475569,color:#0f172a;
    classDef case fill:#fffbeb,stroke:#f59e0b,color:#92400e;
    classDef out fill:#ecfdf5,stroke:#10b981,color:#065f46;
    classDef err fill:#fef2f2,stroke:#ef4444,color:#991b1b;

    Q(["User question<br/>(typed in web chat OR Meet caption)"]):::io --> CHAT["POST /api/chat<br/>IN: messages[] JSON"]:::proc

    CHAT --> RL{"Rate limit<br/>30/hour per IP?"}:::case
    RL -->|exceeded| R429["OUT: 429 Too Many Requests"]:::err
    RL -->|ok| V{"Valid user query?"}:::case
    V -->|"empty messages"| E400a["OUT: 400 No messages"]:::err
    V -->|"no user text"| E400b["OUT: 400 No user query"]:::err
    V -->|yes| RW

    RW["Step 1 — Query rewrite (LLM call #1)<br/>IN: raw query (any language / typos / abbrev)<br/>OUT: cleaned English query<br/>CASE valid 10-400 chars → use rewritten<br/>CASE empty / too long / error → keep original"]:::proc
    RW --> EMB["Step 2 — Embed query<br/>text-embedding-3-large → normalize_L2"]:::proc

    %% Parallel retrieval
    EMB --> SF["Search FEATURES k=15<br/>similarity = cosine (~0 to 1)<br/>→ best_feature_score"]:::proc
    EMB --> SP["Search PROPOSALS k=5<br/>keep chunks scoring > 0.35<br/>→ best_proposal_score"]:::proc

    SF --> DEC{"Routing decision<br/>uses BOTH scores + impl-keyword flag<br/>(implement / deploy / client / proposal ...)"}:::case
    SP --> DEC

    DEC -->|"feature >= 0.55 AND not impl query"| T1["TIER 1 → Feature Catalog<br/>schema FEATURE · badge GREEN"]:::out
    DEC -->|"proposal >= 0.45 OR (impl query AND proposal >= 0.35)"| T2["TIER 2 → Proposals<br/>schema PROPOSAL · badge BLUE"]:::out
    DEC -->|"proposal present but < 0.45"| T2b["TIER 2 → Feature Catalog<br/>(proposals as support) · badge GREEN"]:::out
    DEC -->|"no feature AND no proposal match"| T3["TIER 3 → General AI Knowledge<br/>schema LLM · badge AMBER"]:::out

    T1 --> GEN
    T2 --> GEN
    T2b --> GEN
    T3 --> GEN
    GEN["Step 3 — Generate answer (LLM call #2)<br/>prompt = query + BOTH contexts + chosen schema<br/>OUT: JSON answer"]:::proc

    GEN --> PARSE{"Answer parses as JSON?"}:::case
    PARSE -->|yes| BJ["json_to_blocks → structured cards"]:::proc
    PARSE -->|"no (plain text)"| BT["text_to_blocks → fallback cards"]:::proc

    BJ --> CLR["Color citations + attach source links<br/>green = feature · blue = proposal · amber = AI"]:::proc
    BT --> CLR
    CLR --> RESP["OUT: 200 JSON {badge, blocks}"]:::out
    GEN -.->|"any exception"| E500["OUT: 500 error"]:::err
```

> **Key point — retrieval is parallel, not a cascade.** Both indexes are searched on every query; the thresholds only decide which source the answer leads with. The LLM always receives *both* contexts, so a feature answer can still cite a relevant past proposal.

---

## 3. Delivery modes (same engine, two front-ends)

```mermaid
flowchart TD
    classDef io fill:#eef2ff,stroke:#6366f1,color:#1e1b4b;
    classDef proc fill:#ffffff,stroke:#475569,color:#0f172a;
    classDef out fill:#ecfdf5,stroke:#10b981,color:#065f46;

    Start([User has a question]):::io --> Mode{Which mode?}

    Mode -->|Web mode| W1["Type question in web chat"]:::proc --> RAG
    Mode -->|Online mode| O1["Floating window over Google Meet<br/>reads live captions"]:::proc
    O1 --> O2["Press ▶ Start / ■ Stop to capture<br/>→ click 'Send to RAG'"]:::proc --> RAG

    RAG["RAG engine (/api/chat)<br/>= Phase B above"]:::proc --> AnsW["Web: answer cards"]:::out
    RAG --> AnsO["Online: answer in floating window"]:::out
```

---

## 4. Reference numbers (from the code)

| Aspect | Value / Rule |
|---|---|
| Embedding model | OpenAI `text-embedding-3-large`, 3072-dim |
| Similarity metric | Cosine (vectors `normalize_L2` + FAISS `IndexFlatIP`) |
| Chunk size | ~300 words/chunk, 1-paragraph overlap, discard if < 100 chars |
| Paragraph filter | Keep paragraphs > 60 chars; drop boilerplate (TOC, footers, page numbers) |
| Page references | PDF → `p.N` · PPT → `slide N` · Word → none |
| Retrieval depth | Features k=15 · Proposals k=5 (searched in parallel) |
| Routing thresholds | Feature strong `0.55` · Proposal strong `0.45` · Proposal present `0.35` |
| LLM calls/query | 2 (rewrite + generate) |
| Rate limit | 30 chat requests/hour per IP |

### The 3-tier answer logic
1. **Tier 1 — Feature Catalog** (green): a product feature strongly matches → answer from the catalog.
2. **Tier 2 — Proposals** (blue): a past client proposal matches better, or it's a "what did we implement" question → answer from real proposals.
3. **Tier 3 — General Knowledge** (amber): nothing in the catalog or proposals matches → answer from the AI's general knowledge, clearly labelled as such.

---

## 5. Cost per query

Current setup: **122 features, 413 proposal chunks, LLM = `gpt-4o-mini`, embeddings = `text-embedding-3-large`.**

Every query makes **3 OpenAI API calls**. FAISS search runs locally and is **free** — only the embedding + two LLM calls cost money.

| # | Call | Model | Purpose |
|---|---|---|---|
| 1 | Embed the query | `text-embedding-3-large` | Turn the question into a vector for FAISS search |
| 2 | LLM rewrite | `gpt-4o-mini` | Clean / translate the query |
| 3 | LLM generate | `gpt-4o-mini` | Write the final answer from retrieved context |

### OpenAI unit prices (per 1M tokens)

| Model | Input | Output |
|---|---|---|
| `gpt-4o-mini` (current LLM) | $0.15 | $0.60 |
| `gpt-4o` (pricier option) | $2.50 | $10.00 |
| `text-embedding-3-large` (embeddings) | $0.13 | — |

*Prices as of mid-2026 — confirm on openai.com/api/pricing, they change.*

### Cost per query — current setup (`gpt-4o-mini`)

| Call | Approx. input tokens | Approx. output tokens | Cost |
|---|---|---|---|
| Embed query | ~40 | — | ~$0.000005 |
| LLM rewrite | ~450 | ~40 | ~$0.00009 |
| LLM generate | ~3,500 | ~500 | ~$0.00083 |
| **Total per query** | | | **≈ $0.0009** |

**≈ $0.001 per query (~1,100 queries per $1).** The "generate" call is ~90% of the cost because it carries the 15 retrieved features + up to 5 proposal chunks in its prompt.

### If the LLM were switched to `gpt-4o`

| Call | Cost |
|---|---|
| Embed query | ~$0.000005 |
| LLM rewrite | ~$0.0015 |
| LLM generate | ~$0.0138 |
| **Total per query** | **≈ $0.015** (~65 queries per $1) |

Roughly **16× more expensive** than `gpt-4o-mini`, in exchange for higher answer quality.

### Monthly projection (rough)

| Queries/month | `gpt-4o-mini` | `gpt-4o` |
|---|---|---|
| 1,000 | ~$0.90 | ~$15 |
| 5,000 | ~$4.50 | ~$75 |
| 20,000 | ~$18 | ~$300 |

### One-time cost: rebuilding the index

Only when content changes and everything is re-embedded:
122 features (~15K tokens) + 413 chunks (~165K tokens) ≈ **180K tokens** × $0.13/1M ≈ **$0.02 per full rebuild** (~2 cents). Negligible.

> **Caveat:** token counts are estimates; the "generate" prompt size varies with how long the feature descriptions and proposal chunks are, so real cost can swing ±30–50%. OpenAI's dashboard shows exact usage.

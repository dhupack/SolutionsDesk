# SolutionsDesk Chatbot — Complete Workflow

A single end-to-end view of the RAG chatbot for a non-code audience:

- **Phase A — Indexing SOP** (offline): how source documents become searchable vectors (chunking strategy, embeddings, FAISS).
- **Phase A-Live — Update catalogue from Google Sheet** (live): a one-click rebuild that re-embeds the feature catalogue from a Google Sheet, with no redeploy.
- **Phase B — Query Workflow** (live): how a question becomes an answer (greeting guard → rewrite → parallel retrieval **with rollup** → routing → generation → render).
- **Delivery modes**: Web Chat and Online (Google Meet) mode.

> Embeddings: OpenAI `text-embedding-3-large` (3072-dim) · LLM: OpenAI `gpt-4o-mini` (configurable) · Vector store: FAISS (cosine similarity).
> Feature catalogue source: **Google Sheet** (tabs `XSWIFT_Feature_Catalogue` + `CPL_Feature_Catalogue`); local `*.xlsx` is a dev fallback.
> Hosting: Render free tier (512 MB) — `torch`/`transformers` are blocked at startup to stay within memory.

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
        FA["IN: Google Sheet (XSWIFT + CPL tabs)<br/>or data/feature_sheet/*.xlsx (dev fallback)"]:::io
        FA --> FB["Read each row (CSV export, stdlib csv)<br/>1 row = 1 feature"]:::proc
        FB --> FC["Build text per feature:<br/>name x2 + Module + Bucket +<br/>What it does + Business Value +<br/>Sales Talking Point + Dependencies"]:::proc
        FC --> FD["Embed → text-embedding-3-large<br/>(3072-dim vector)"]:::proc
        FD --> FE["normalize_L2 → FAISS IndexFlatIP<br/>(inner product = cosine)"]:::proc
        FE --> FF["OUT: feature_index.faiss +<br/>feature_metadata.json<br/>(feature_id, name, full_row)"]:::out
    end

    %% ---------- Proposals ----------
    subgraph PROP["A2 — Proposal index (heading-aware hierarchical chunking)"]
        direction TB
        PA["IN: data/raw_proposals/&lt;client&gt;/*<br/>folder = client · PDF / PPT / Word only (no xlsx)<br/>CASE: skip RFQ/ folders + *commercial* / *cost estimate* files"]:::io
        PA --> PT{"File type?"}:::case
        PT -->|PDF| P_PDF["Detect NUMBERED headings (1, 1.2, 2.2.1) from text<br/>CASE: per-page density guard — a page with 4+<br/>integer 'headings' is a numeric table → demote rows"]:::case
        PT -->|PPT / PPTX| P_PPT["One section per slide<br/>title = heading · all shape text = body"]:::case
        PT -->|DOC / DOCX| P_DOC["Headings from styles (Heading 1/2/3)<br/>Tables linearized to 'col: val | col: val' rows"]:::case

        P_PDF --> PTREE
        P_PPT --> PTREE
        P_DOC --> PTREE
        PTREE["Build SECTION TREE (heading + its body)<br/>CASE: small section → 1 chunk<br/>CASE: split leaf &gt; 350 words at paragraphs<br/>CASE: merge tiny sibling sections (&lt; 80 words)<br/>CASE: stitch a section across page breaks<br/>CASE: no headings (scanned/un-styled) → synthetic 'Introduction'<br/>CASE: drop boilerplate + image-only sections"]:::case

        PTREE --> PIND["Detect industry:<br/>1) client-name map → 2) content keywords<br/>→ else 'logistics'"]:::proc
        PIND --> PEMB["embed_text = 'Client | Industry | Section breadcrumb | File:' + chunk<br/>→ embed (3072-dim) → normalize_L2 → IndexFlatIP"]:::proc
        PEMB --> POUT["OUT: proposal_index.faiss +<br/>proposal_metadata.json<br/>(client, file, industry, page_ref, content,<br/>section_path, parent_id, breadcrumb, group_key)"]:::out
    end
```

> **Why heading-aware (not a fixed 300-word window):** chunk boundaries follow the document's own section structure, so each chunk is a complete idea. Every chunk records its `section_path` (e.g. `2.2.1`), its `parent_id` (the section above it), and a `breadcrumb` — which lets retrieval later **roll a matched chunk up to its whole section** (see Phase B). Numbered-heading detection works even on flat PDF text; a per-page density guard stops numeric tables (Gantt charts, BOQ, spec sheets) from masquerading as headings.

---

## 1-Live. Update catalogue from Google Sheet (one click, no redeploy)

The feature catalogue lives in a **Google Sheet** (tabs `XSWIFT_Feature_Catalogue` + `CPL_Feature_Catalogue`). A non-developer adds or edits rows, clicks one button in the Sheet, and the **live** chatbot re-embeds the whole catalogue — no git, no laptop, no manual `setup.py`. (Setup steps + the Apps Script live in [`docs/gsheet_rebuild_button.md`](gsheet_rebuild_button.md).)

```mermaid
flowchart TD
    classDef io fill:#eef2ff,stroke:#6366f1,color:#1e1b4b;
    classDef proc fill:#ffffff,stroke:#475569,color:#0f172a;
    classDef case fill:#fffbeb,stroke:#f59e0b,color:#92400e;
    classDef out fill:#ecfdf5,stroke:#10b981,color:#065f46;
    classDef err fill:#fef2f2,stroke:#ef4444,color:#991b1b;

    G["Editor adds / edits rows in Google Sheet<br/>(XSWIFT + CPL tabs)"]:::io
    G --> BTN["Clicks '🔄 Update chatbot'<br/>(Apps Script menu button)"]:::proc
    BTN --> POST["POST /api/rebuild-catalog<br/>header: X-Rebuild-Token"]:::proc
    POST --> AUTH{"token matches<br/>REBUILD_TOKEN?"}:::case
    AUTH -->|no| E401["OUT: 401 Unauthorized"]:::err
    AUTH -->|yes| BG["Start rebuild in background thread<br/>→ return 202 immediately<br/>(avoids worker timeout)"]:::out

    BG --> PULL["Pull both tabs via CSV export (per-tab gid)<br/>stdlib csv — no pandas/torch (512MB safe)"]:::proc
    PULL --> EMB["Embed ~123 rows → text-embedding-3-large<br/>→ normalize_L2 → IndexFlatIP (~7s)"]:::proc
    EMB --> SAVE["Write feature_index.faiss +<br/>feature_metadata.json"]:::proc
    SAVE --> SWAP["Reload feature index into the live app<br/>(in memory — next query uses it)"]:::out
    SWAP --> GIT{"index changed<br/>vs committed?"}:::case
    GIT -->|yes| PUSH["git commit + push to GitHub<br/>→ auto-deploy bakes it in<br/>(survives Render restart)"]:::out
    GIT -->|no| NOOP["skip push<br/>('No index changes to commit')"]:::proc

    BTN -.->|"polls every 3s"| STAT["GET /api/rebuild-status<br/>→ toast '✅ 123 features live'"]:::proc
```

> **Why background + CSV (not a blocking pandas read):** a synchronous rebuild on the 512 MB free tier could exceed gunicorn's 120 s timeout (cold start) and OOM the worker. So the request returns `202` at once and the work runs in a thread; the catalogue is pulled as CSV (no pandas) and `torch`/`transformers` are blocked at startup — together these keep the rebuild well under 512 MB. **Edits and additions both apply** (the whole catalogue is re-embedded). Click *after* finishing a row — the button never fires on its own, so partial rows are never embedded.

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
    V -->|yes| GREET{"Step 0 — Greeting / small-talk only?<br/>whole message is hi / thanks / ok / good morning ...<br/>(real queries like 'hi i want truck tracking' pass through)"}:::case

    GREET -->|yes| GRESP["Short-circuit: SKIP rewrite + retrieval<br/>→ friendly one-liner, NO solutions"]:::out
    GREET -->|no| RW

    RW["Step 1 — Query rewrite (LLM call #1)<br/>IN: raw query (any language / typos / abbrev)<br/>OUT: cleaned English query<br/>CASE valid 3-400 chars → use rewritten<br/>CASE empty / too long / error → keep original"]:::proc
    RW --> EMB["Step 2 — Embed query<br/>text-embedding-3-large → normalize_L2"]:::proc

    %% Parallel retrieval with rollup
    EMB --> SF["Search FEATURES k=15<br/>+ BUCKET ROLLUP: pull the matched feature's<br/>bucket-mates (whole area toolkit, up to 3 buckets)<br/>→ best_feature_score"]:::proc
    EMB --> SP["Search PROPOSALS k=5<br/>+ SIBLING ROLLUP: pull the other children of the<br/>hit's parent section + the parent intro<br/>→ best_proposal_score"]:::proc

    SF --> DEC{"Routing decision<br/>uses BOTH scores + impl-keyword flag<br/>(implement / deploy / client / solution for ...)"}:::case
    SP --> DEC

    DEC -->|"feature >= 0.43 AND not impl query"| T1["TIER 1 → Feature Catalog<br/>schema FEATURE · badge GREEN"]:::out
    DEC -->|"proposal >= 0.43 OR (impl query AND proposal >= 0.36)"| T2["TIER 2 → Proposals<br/>+ rolled-up feature toolkit<br/>schema PROPOSAL · badge BLUE"]:::out
    DEC -->|"proposal present (> 0.36)"| T2b["TIER 2 → Feature Catalog<br/>(proposals as support) · badge GREEN"]:::out
    DEC -->|"strong feature (>= 0.43), impl-phrased, no proposal"| T2c["TIER 2 → Feature Catalog<br/>(fallback — don't drop to General) · badge GREEN"]:::out
    DEC -->|"nothing matches"| T3["TIER 3 → General AI Knowledge<br/>schema LLM · badge AMBER"]:::out

    GRESP --> GEN
    T1 --> GEN
    T2 --> GEN
    T2b --> GEN
    T2c --> GEN
    T3 --> GEN
    GEN["Step 3 — Generate answer (LLM call #2)<br/>prompt = query + BOTH contexts + chosen schema<br/>(greeting path: a short conversational prompt instead)<br/>OUT: JSON answer (or plain text for greetings)"]:::proc

    GEN --> PARSE{"Answer parses as JSON?"}:::case
    PARSE -->|yes| BJ["json_to_blocks → structured cards"]:::proc
    PARSE -->|"no (plain text)"| BT["text_to_blocks → fallback cards"]:::proc

    BJ --> CLR["Color citations + attach source links<br/>green = feature (→ Google Sheet tab) ·<br/>blue = proposal (→ doc) · amber = AI"]:::proc
    BT --> CLR
    CLR --> RESP["OUT: 200 JSON {badge, blocks}"]:::out
    GEN -.->|"any exception"| E500["OUT: 500 error"]:::err
```

> **Key point — retrieval is parallel, not a cascade.** Both indexes are searched on every query; the thresholds only decide which source the answer leads with. The LLM always receives *both* contexts, so a feature answer can still cite a relevant past proposal.
>
> **Three recent refinements:**
> - **Greeting guard (Step 0):** a message that is *entirely* small-talk ("hi", "thanks", "good morning") skips rewrite + retrieval and gets a one-line reply — otherwise the rewriter would invent a query (e.g. "hi" → "logistics software") and return irrelevant solutions.
> - **Rollup at retrieval:** a feature hit pulls in its **bucket-mates** (the whole area toolkit, e.g. all *CPL - Weighbridge* features); a proposal hit pulls in its **sibling sections** under the same parent. So umbrella questions get the full set, not one fragment.
> - **Feature toolkit in the proposal tier + a fallback:** Tier 2 (proposal) answers now also surface the rolled-up feature toolkit, and a strong feature match is never dropped to General Knowledge just because the query was phrased like "solution for …".

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
| Proposal chunking | **Heading-aware**: section tree per file; split leaf > 350 words, merge sibling sections < 80 words, drop chunks < 60 chars |
| Heading detection | PDF → numbered headings (+ per-page table-density guard) · Word → heading styles · PPT → one section/slide |
| Per-chunk metadata | `section_path`, `parent_id`, `breadcrumb`, `page_ref`, `group_key` |
| Page references | PDF → `p.N` · PPT → `slide N` · Word → none |
| Retrieval depth | Features k=15 **+ bucket rollup** (≤3 buckets) · Proposals k=5 **+ sibling rollup** (≤2 parents) |
| Routing thresholds | Feature strong `0.43` · Proposal strong `0.43` · Proposal present `0.36` |
| Greeting guard | Whole-message small-talk → skip rewrite + retrieval (no solutions) |
| LLM calls/query | 2 (rewrite + generate); greeting path = 1 (generate only) |
| Rate limit | 30 chat requests/hour per IP |

### The 3-tier answer logic
0. **Greeting / small-talk** (no badge): the whole message is a greeting → reply conversationally, skip retrieval entirely.
1. **Tier 1 — Feature Catalog** (green): a product feature strongly matches → answer from the catalog. The matched feature's **bucket-mates** are rolled in so you get the whole area toolkit.
2. **Tier 2 — Proposals** (blue): a past client proposal matches better, or it's a "what did we implement" question → answer from real proposals, **plus** the rolled-up feature toolkit for the area.
3. **Tier 3 — General Knowledge** (amber): nothing in the catalog or proposals matches → answer from the AI's general knowledge, clearly labelled. *A strong feature match is never demoted here just because the query said "solution for …".*

---

## 5. Cost per query

Current setup: **123 features, 385 proposal chunks, LLM = `gpt-4o-mini`, embeddings = `text-embedding-3-large`.**

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

**≈ $0.001 per query (~1,100 queries per $1).** The "generate" call is ~90% of the cost because it carries the retrieved features + proposal chunks in its prompt — and **rollup** can add the rest of a matched bucket / section, so a broad "solution" query carries more context (and costs a bit more) than a narrow one. Greeting messages skip retrieval, so they cost only the single generate call.

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
123 features (~15K tokens) + 385 chunks (~155K tokens) ≈ **170K tokens** × $0.13/1M ≈ **$0.02 per full rebuild** (~2 cents). Negligible.

A feature-only rebuild (the Google Sheet "🔄 Update chatbot" button) re-embeds just the 123 features (~15K tokens) ≈ **$0.002 per click** (~0.2 cents). Identical re-clicks still re-embed but skip the git push (no change to commit).

> **Caveat:** token counts are estimates; the "generate" prompt size varies with how long the feature descriptions and proposal chunks are, so real cost can swing ±30–50%. OpenAI's dashboard shows exact usage.

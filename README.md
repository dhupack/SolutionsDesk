# RAG Pipeline - Employee Onboarding Chatbot

A **3-tier hierarchical Retrieval-Augmented Generation (RAG)** system for employee onboarding. The chatbot learns from feature documentation and proposal documents, providing intelligent answers with proper source citations.

## Architecture

```
Query
  ↓
[Tier 1] Feature Excel Sheet → Found? Return with feature reference
  ↓ (No)
[Tier 2] Proposal Documents → Found? Return with proposal reference
  ↓ (No)
[Tier 3] LLM + Document Context → Return with reasoning
```

## Features

✅ **Automated Document Processing**
- Download proposals from Google Drive
- Extract Problem & Solution sections from PDFs, PPTs, Word docs
- Convert to markdown format with metadata

✅ **Semantic Search with FAISS**
- Separate FAISS indices for Features and Proposals
- OpenAI embeddings (text-embedding-3-small)
- Fast local vector similarity search

✅ **LangGraph Workflow with Persistence**
- State-based workflow: Tier1 → Tier2 → Tier3
- Persistent conversation history (SqliteSaver)
- Multi-turn dialogue support

✅ **Interactive CLI Chatbot**
- Multi-turn conversation
- Source citations (with row/column or file references)
- Conversation history & persistence
- Commands: `history`, `clear`, `quit`

## Project Structure

```
Rag_feature/
├── data/
│   ├── feature_sheet/           # Excel feature files (you upload)
│   ├── raw_proposals/           # Downloaded PDFs/PPTs/Word docs
│   └── extracted_proposals/     # Auto-extracted markdown files
├── embeddings/
│   ├── feature_index.faiss      # Feature FAISS index
│   ├── feature_metadata.json    # Feature metadata
│   ├── proposal_index.faiss     # Proposal FAISS index
│   └── proposal_metadata.json   # Proposal metadata
├── conversations/
│   └── workflow_checkpoints/    # Persistent conversation state
├── src/
│   ├── extraction/              # Document parsing & extraction
│   │   ├── document_parser.py       → Extract text from PDFs/PPTs/Word
│   │   ├── section_identifier.py    → Detect Problem/Solution sections
│   │   ├── markdown_converter.py    → Convert to markdown
│   │   └── extraction_pipeline.py   → Orchestrator
│   ├── loaders/                 # Data loading & embedding
│   │   ├── feature_loader.py        → Load & embed Excel features
│   │   └── proposal_loader.py       → Load & embed proposals
│   ├── retrieval/               # 3-tier retrieval logic
│   │   └── tier_retrieval.py        → Tier1/2/3 queries
│   ├── rag/                     # LangGraph workflow
│   │   └── langgraph_workflow.py    → State machine + persistence
│   └── cli/                     # Interactive chatbot
│       └── chatbot.py               → CLI interface
├── config.py                    # Configuration
├── setup.py                     # Initialize pipeline
├── main.py                      # Run chatbot
└── requirements.txt             # Dependencies
```

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set OpenAI API Key

```bash
# Windows
set OPENAI_API_KEY=your_openai_api_key

# Linux/Mac
export OPENAI_API_KEY=your_openai_api_key
```

### 3. Upload Excel Feature Files

1. Create folder: `data/feature_sheet/`
2. Upload 2 Excel files with sheet name: `Feature catalogue`
3. Expected columns:
   - Feature ID
   - Feature Name
   - Bucket
   - Feature Type
   - Module / Area
   - What it does
   - Business Value / Impact
   - Dependencies / Inputs
   - Sales Talking Point

### 4. Run Setup (to download and extract proposals + build indices)

```bash
python setup.py
```

This will:
- ✅ Step 1: Download proposals from Google Drive folder
- ✅ Step 2: Extract Problem/Solution sections → markdown files
- ✅ Step 3: Build FAISS index for Feature Sheet
- ✅ Step 4: Build FAISS index for Proposal documents

**Note:** If `setup.py` fails at Step 1 (Google Drive download), you can:
- Manually download files from the Google Drive folder
- Place them in: `data/raw_proposals/`
- Then continue with `setup.py` (it will skip download and proceed to extraction)

### 5. Run the Chatbot

```bash
python main.py
```

## Usage

### Interactive CLI

```
You: What is the feature for real-time tracking?

✅ Answer (Tier 1):
---
Feature: Real-Time Tracking Module

Provides real-time vehicle tracking with GPS integration across all locations.

Business Value: Enhanced visibility, reduced delays, improved efficiency
---
📚 [Source: Feature_catalogue.xlsx, Row 7]


You: What are the benefits of the ABC proposal?

✅ Answer (Tier 2):
---
From ABC Corp Proposal

Key benefits include improved operational efficiency by 25%, cost reduction through automation,
and enhanced reporting capabilities with real-time dashboards.
---
📚 [Source: abc_corp_proposal.md (solution section)]


You: How do I implement a distributed system?

✅ Answer (Tier 3):
---
A distributed system involves multiple computers communicating over a network...

Why this solution: Based on industry best practices from your proposal documents
and modern architectural patterns...

How to implement: Start with message queues, use load balancing...
---
📚 [Source: Knowledge-based answer from LLM (based on document context)]

Commands:
  history → Show conversation history
  clear → Clear conversation history
  quit → Exit
```

## Configuration

Edit `config.py` to customize:

```python
SIMILARITY_THRESHOLD = 0.7      # Min similarity score to consider "found"
TOP_K_RESULTS = 3              # Results to retrieve per tier
GOOGLE_DRIVE_FOLDER_ID = "..."  # Your Google Drive folder
EMBEDDING_MODEL = "text-embedding-3-small"
LLM_MODEL = "gpt-4"
```

## Key Modules

### Extraction Pipeline (`src/extraction/`)

| Module | Purpose |
|--------|---------|
| `document_parser.py` | Extract text from PDF, PPT, Word formats |
| `section_identifier.py` | Detect Problem, Solution, Feature sections using keyword heuristics |
| `markdown_converter.py` | Convert extracted sections to markdown with metadata |
| `extraction_pipeline.py` | Orchestrator: download → parse → extract → save |

### Data Loaders (`src/loaders/`)

| Module | Purpose |
|--------|---------|
| `feature_loader.py` | Load Excel features → create FAISS index |
| `proposal_loader.py` | Load markdown proposals → create separate FAISS index |

### Retrieval (`src/retrieval/`)

| Module | Purpose |
|--------|---------|
| `tier_retrieval.py` | Implement Tier1/2/3 query logic with thresholds |

### RAG Workflow (`src/rag/`)

| Module | Purpose |
|--------|---------|
| `langgraph_workflow.py` | LangGraph state machine with 5 nodes: Query Tier1 → Tier2 → Tier3 → Format → Save |

### CLI (`src/cli/`)

| Module | Purpose |
|--------|---------|
| `chatbot.py` | Interactive terminal interface |

## Response Format

### Tier 1 (Feature Sheet)

```
Feature: [Feature Name]

[What it does]

Business Value: [Business Value/Impact]

[Source: Feature_catalogue.xlsx, Row X]
```

### Tier 2 (Proposal Documents)

```
[Problem/Solution content from proposal]

[Source: proposal_filename.md (problem/solution section)]
```

### Tier 3 (LLM with Reasoning)

```
[LLM-generated answer]

Why this solution: [Reasoning from documents]

How to implement: [Step-by-step guidance]

[Source: Knowledge-based answer from LLM (based on document context)]
```

## Troubleshooting

### Issue: "No Excel files found"
- **Solution:** Upload Excel files to `data/feature_sheet/` and ensure sheet name is `Feature catalogue`

### Issue: "Index not found"
- **Solution:** Run `python setup.py` to build indices

### Issue: "No markdown files found"
- **Solution:** Run `python setup.py` to extract proposals from PDF/PPT/Word files

### Issue: "OPENAI_API_KEY not set"
- **Solution:** Set environment variable before running:
  ```bash
  set OPENAI_API_KEY=your_key  # Windows
  export OPENAI_API_KEY=your_key  # Linux/Mac
  ```

### Issue: Google Drive download fails
- **Solution:** Manually download files from Google Drive and place in `data/raw_proposals/`

## Performance Notes

- **Feature Search:** O(1) - FAISS index lookup with cosine similarity
- **Proposal Search:** O(1) - Separate FAISS index with section-level granularity
- **Embedding Creation:** ~10-20ms per document (OpenAI API)
- **LLM Response:** ~2-5 seconds (GPT-4)

## Persistence

- **Conversation History:** Stored in `conversations/workflow_checkpoints/rag_checkpoints.db`
- **Indices:** Saved to `embeddings/` directory
- **Metadata:** JSON files track feature rows, proposal sections, extraction logs

## Future Enhancements

- [ ] Support for multiple language embedding models
- [ ] Hybrid search (semantic + keyword)
- [ ] Custom similarity thresholds per tier
- [ ] Conversation summarization
- [ ] Web UI interface
- [ ] Export conversation logs
- [ ] Batch query processing

## License

MIT

## Support

For issues or questions, check:
1. `setup.log` - Setup process logs
2. `chatbot.log` - Runtime logs
3. `config.py` - Configuration settings

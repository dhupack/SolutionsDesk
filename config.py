import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
FEATURE_SHEET_DIR = DATA_DIR / "feature_sheet"
RAW_PROPOSALS_DIR = DATA_DIR / "raw_proposals"
EXTRACTED_PROPOSALS_DIR = DATA_DIR / "extracted_proposals"
EMBEDDINGS_DIR = PROJECT_ROOT / "embeddings"
CONVERSATIONS_DIR = PROJECT_ROOT / "conversations"

for directory in [DATA_DIR, FEATURE_SHEET_DIR, RAW_PROPOSALS_DIR, EXTRACTED_PROPOSALS_DIR, EMBEDDINGS_DIR, CONVERSATIONS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# ── Providers ──────────────────────────────────────────────────────────────────
# Switch backends without touching code: set these in .env.
#   EMBEDDING_PROVIDER = openai | local      LLM_PROVIDER = openai | groq
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai")
LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "openai")

# Groq LLM Configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL = "llama-3.3-70b-versatile"

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")          # or "gpt-4o"
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")  # or "text-embedding-3-large"

# Embedding — local sentence-transformers fallback (no API key needed)
EMBEDDING_MODEL = "all-mpnet-base-v2"


def get_embeddings():
    """Return the configured embeddings backend (OpenAI or local sentence-transformers)."""
    if EMBEDDING_PROVIDER == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL, api_key=OPENAI_API_KEY)
    from langchain_huggingface import HuggingFaceEmbeddings
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


def get_llm(temperature: float = 0.2):
    """Return the configured chat LLM (OpenAI or Groq)."""
    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=OPENAI_LLM_MODEL, api_key=OPENAI_API_KEY, temperature=temperature)
    from langchain_groq import ChatGroq
    return ChatGroq(model=LLM_MODEL, api_key=GROQ_API_KEY, temperature=temperature)

# FAISS index paths
FEATURE_FAISS_INDEX_PATH = EMBEDDINGS_DIR / "feature_index.faiss"
FEATURE_METADATA_PATH = EMBEDDINGS_DIR / "feature_metadata.json"
PROPOSAL_FAISS_INDEX_PATH = EMBEDDINGS_DIR / "proposal_index.faiss"
PROPOSAL_METADATA_PATH = EMBEDDINGS_DIR / "proposal_metadata.json"

# Retrieval
SIMILARITY_THRESHOLD = 0.35       # Tier 1 (feature sheet) — hybrid score, can stay lower
TIER2_SIMILARITY_THRESHOLD = 0.45 # Tier 2 (proposals) — stricter, new joinee must not get vague answers
TOP_K_RESULTS = 3

# Google Drive
GOOGLE_DRIVE_FOLDER_ID = "1NEV2F6BktyaSpoX_BrKv2NWJzg0khqab"
EXTRACTION_OUTPUT_DIR = EXTRACTED_PROPOSALS_DIR
EXTRACTION_METADATA_PATH = DATA_DIR / "extraction_metadata.json"

# LangGraph
CHECKPOINT_DIR = CONVERSATIONS_DIR
MAX_CONVERSATION_HISTORY = 10

# Feature Excel
FEATURE_SHEET_NAME = "Feature catalogue"
FEATURE_COLUMNS = [
    "Feature ID",
    "Feature Name",
    "Bucket",
    "Feature Type",
    "Module / Area",
    "What it does",
    "Business Value / Impact",
    "Dependencies / Inputs",
    "Sales Talking Point"
]

# Section extraction keywords
PROBLEM_KEYWORDS = ["problem", "challenge", "issue", "pain point", "our understanding", "scope", "business process"]
SOLUTION_KEYWORDS = ["solution", "technical specification", "approach", "methodology", "implementation", "how it works"]
FEATURE_KEYWORDS = ["feature", "capability", "function", "module", "component"]

LOG_LEVEL = "INFO"

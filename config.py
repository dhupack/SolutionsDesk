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
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")  # 3072-dim — must match the committed FAISS indexes

# Other embedding options — disabled (kept for reference):
#   text-embedding-3-small        # OpenAI, 1536-dim — would require rebuilding the FAISS indexes
#   EMBEDDING_MODEL = "all-mpnet-base-v2"   # local sentence-transformers, 768-dim — would require rebuilding the FAISS indexes


def get_embeddings():
    """Return the OpenAI embeddings backend (text-embedding-3-large)."""
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model=OPENAI_EMBEDDING_MODEL, api_key=OPENAI_API_KEY)
    # Local fallback — disabled (see the commented EMBEDDING_MODEL above):
    # from langchain_huggingface import HuggingFaceEmbeddings
    # return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


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

# ── Feature catalogue source: Google Sheet (production) ─────────────────────────
# When FEATURE_SHEET_GSHEET_ID is set, the feature index is (re)built by pulling
# this Google Sheet's tabs instead of the local Excel files. The Sheet must be
# shared "Anyone with the link → Viewer" so the server can download it unauthenticated.
# The whole workbook is fetched once as .xlsx (export?format=xlsx) and every tab is
# read by name — this is reliable, unlike Google's per-tab CSV export which silently
# falls back to the first tab.
FEATURE_SHEET_GSHEET_ID = os.getenv("FEATURE_SHEET_GSHEET_ID", "1XguMyC67fsc73Ujpv2YDOFApE6Ztt6klTMbMUgrOJ1s")
# Tabs to read from the workbook. Empty/None means "read every tab".
FEATURE_SHEET_TABS = ["XSWIFT_Feature_Catalogue", "CPL_Feature_Catalogue"]
# Per-tab gids for the reliable CSV export (export?format=csv&gid=<gid>). This path
# uses only the stdlib `csv` module — NO pandas/openpyxl — so the rebuild stays well
# under Render's 512MB limit (importing pandas at runtime was OOM-killing the worker).
FEATURE_SHEET_TAB_GIDS = {
    "XSWIFT_Feature_Catalogue": os.getenv("FEATURE_SHEET_XSWIFT_GID", "0"),
    "CPL_Feature_Catalogue":    os.getenv("FEATURE_SHEET_CPL_GID", "1728231193"),
}
FEATURE_SHEET_XLSX_URL = (
    f"https://docs.google.com/spreadsheets/d/{FEATURE_SHEET_GSHEET_ID}/export?format=xlsx"
    if FEATURE_SHEET_GSHEET_ID else ""
)
# Public Sheet URL for citation "view source" links (option a). Per-tab gids are
# filled in once read off each tab's URL; falls back to the workbook URL if unknown.
FEATURE_SHEET_VIEW_URL = (
    f"https://docs.google.com/spreadsheets/d/{FEATURE_SHEET_GSHEET_ID}/edit"
    if FEATURE_SHEET_GSHEET_ID else ""
)
FEATURE_SHEET_TAB_GID = {
    "XSWIFT": os.getenv("FEATURE_SHEET_XSWIFT_GID", "0"),           # XSWIFT_Feature_Catalogue tab
    "CPL":    os.getenv("FEATURE_SHEET_CPL_GID", "1728231193"),     # CPL_Feature_Catalogue tab
}

# ── Rebuild endpoint + git write-back (option 2) ────────────────────────────────
# REBUILD_TOKEN protects POST /api/rebuild-catalog. GITHUB_TOKEN lets the running
# server commit the freshly built index back to the repo so it survives restarts.
REBUILD_TOKEN = os.getenv("REBUILD_TOKEN", "")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")
# owner/repo for the authenticated push URL; auto-detected from `git remote` if empty.
GITHUB_REPO   = os.getenv("GITHUB_REPO", "")

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

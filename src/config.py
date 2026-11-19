"""Central configuration. Values come from the .env file (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "citeverify.db"

# ---- Free LLM settings (any OpenAI-compatible endpoint) ----
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "none").strip().lower()  # groq | gemini | ollama | none
_PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "ollama": ("http://localhost:11434/v1", "llama3.1:8b"),
}
_base, _model = _PRESETS.get(LLM_PROVIDER, ("", ""))
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = (os.getenv("LLM_BASE_URL") or _base).strip().rstrip("/")
LLM_MODEL = (os.getenv("LLM_MODEL") or _model).strip()


def llm_available() -> bool:
    """True when a free LLM provider is configured (Ollama needs no key)."""
    if LLM_PROVIDER == "none" or not LLM_BASE_URL or not LLM_MODEL:
        return False
    return LLM_PROVIDER == "ollama" or bool(LLM_API_KEY)


CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "citeverify@example.com").strip()
S2_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
OUTDATED_YEARS = int(os.getenv("OUTDATED_YEARS", "10"))
USE_EMBEDDINGS = os.getenv("USE_EMBEDDINGS", "false").lower() == "true"

HTTP_TIMEOUT = 20
USER_AGENT = f"CiteVerify/1.0 (mailto:{CONTACT_EMAIL})"
MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 60

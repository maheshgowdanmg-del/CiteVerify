"""Configuration module for CiteVerify.
Loads environment variables, API endpoints, model parameters, and database paths.
Supports multi-provider AI architecture (Google Gemini, Groq, Offline).
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def get_secret(key: str, default: str = "") -> str:
    """Helper to read from environment or Streamlit Cloud st.secrets."""
    val = os.getenv(key, "")
    if val:
        return val.strip()
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            return str(st.secrets[key]).strip()
    except Exception:
        pass
    return default


# ------------------------------------------------------------------------------
# AI Provider Settings (Gemini / Groq / Offline)
# ------------------------------------------------------------------------------
LLM_PROVIDER = get_secret("LLM_PROVIDER", "gemini").lower().strip()
LLM_API_KEY = (
    get_secret("LLM_API_KEY") or
    get_secret("GEMINI_API_KEY") or
    get_secret("GROQ_API_KEY")
).strip()
LLM_MODEL = get_secret("LLM_MODEL", "").strip()
LLM_BASE_URL = get_secret("LLM_BASE_URL", "").strip()
DEFAULT_TEMPERATURE = float(get_secret("GEMINI_TEMPERATURE", get_secret("LLM_TEMPERATURE", "0.2")))

# Legacy backward compatibility aliases
GEMINI_API_KEY = LLM_API_KEY
GEMINI_MODEL = LLM_MODEL or "gemini-2.5-flash"


def get_active_provider() -> str:
    """Return the active AI provider ('gemini', 'groq', or 'offline')."""
    prov = get_secret("LLM_PROVIDER", LLM_PROVIDER or "gemini").lower().strip()
    if prov in ["gemini", "groq", "offline"]:
        return prov
    return "gemini"


def get_active_api_key() -> str:
    """Return the active provider API key."""
    prov = get_active_provider()
    if prov == "gemini":
        return (get_secret("GEMINI_API_KEY") or get_secret("LLM_API_KEY") or LLM_API_KEY).strip()
    elif prov == "groq":
        return (get_secret("GROQ_API_KEY") or get_secret("LLM_API_KEY") or LLM_API_KEY).strip()
    return ""


def get_active_model() -> str:
    """Return the active model name based on provider."""
    prov = get_active_provider()
    explicit = get_secret("LLM_MODEL", LLM_MODEL).strip()
    if explicit:
        return explicit
    if prov == "gemini":
        return get_secret("GEMINI_MODEL", "gemini-2.5-flash").strip()
    elif prov == "groq":
        return "llama-3.3-70b-versatile"
    return "rule-engine"


def is_ai_configured() -> bool:
    """Check if the active AI provider is ready for online inference."""
    prov = get_active_provider()
    if prov == "offline":
        return False
    key = get_active_api_key()
    return bool(key and len(key) > 5 and not key.startswith("your_"))


def is_gemini_configured() -> bool:
    """Legacy compatibility check."""
    return is_ai_configured()


# ------------------------------------------------------------------------------
# Database & Network Settings
# ------------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "citeverify.db"))

# Scholarly API endpoints
CROSSREF_API_URL = "https://api.crossref.org/works"
OPENALEX_API_URL = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "researcher@citeverify.org").strip()
USER_AGENT = f"CiteVerify/2.0 (mailto:{CONTACT_EMAIL}; Academic Verification Bot)"

# Processing limits
MAX_CLAIMS_DEFAULT = 25
REQUEST_TIMEOUT = 12  # seconds per HTTP call
OUTDATED_YEARS_THRESHOLD = 10


# ------------------------------------------------------------------------------
# 5 Canonical Verdict Definitions & Color Codes
# ------------------------------------------------------------------------------
VERDICTS = {
    "SUPPORTED": {
        "label": "Supported",
        "color": "#14B8A6",  # Teal (#14B8A6)
        "bg": "#F0FDFA",
        "icon": "✅",
        "desc": "The evidence directly supports the claim within the source's research context."
    },
    "PARTIALLY_SUPPORTED": {
        "label": "Partially Supported",
        "color": "#D6B56D",  # Gold (#D6B56D)
        "bg": "#FEFCE8",
        "icon": "⚠️",
        "desc": "The evidence supports some aspects but not the complete claim, or conditions differ."
    },
    "UNSUPPORTED": {
        "label": "Unsupported",
        "color": "#E11D48",  # Deep Red
        "bg": "#FFF1F2",
        "icon": "❌",
        "desc": "The retrieved evidence does not justify the claim, or actively disproves it."
    },
    "CONTRADICTORY": {
        "label": "Contradictory",
        "color": "#8B5CF6",  # Purple
        "bg": "#F5F3FF",
        "icon": "⚡",
        "desc": "The source evidence directly conflicts with the claim or demonstrates opposing trial outcomes."
    },
    "NEEDS_REVIEW": {
        "label": "Needs Review",
        "color": "#64748B",  # Muted grey (#64748B)
        "bg": "#F8FAFC",
        "icon": "👁️",
        "desc": "Evidence, retrieval or source matching is insufficient for a reliable algorithmic decision."
    }
}

# Aliases for backwards compatibility with legacy database rows or alternate casings
VERDICTS["REFUTED"] = VERDICTS["UNSUPPORTED"]
VERDICTS["NOT_ENOUGH_EVIDENCE"] = VERDICTS["NEEDS_REVIEW"]


def normalize_verdict(raw: str) -> str:
    """Normalize any verdict variant into one of the 5 canonical verdict keys."""
    if not raw:
        return "NEEDS_REVIEW"
    key = str(raw).strip().upper().replace(" ", "_")
    aliases = {
        "REFUTED": "UNSUPPORTED",
        "NOT_ENOUGH_EVIDENCE": "NEEDS_REVIEW",
        "CANNOT_VERIFY": "NEEDS_REVIEW",
        "UNVERIFIED": "NEEDS_REVIEW",
        "PARTIALLY_SUPPORTED": "PARTIALLY_SUPPORTED",
        "SUPPORTED": "SUPPORTED",
        "UNSUPPORTED": "UNSUPPORTED",
        "CONTRADICTORY": "CONTRADICTORY",
        "NEEDS_REVIEW": "NEEDS_REVIEW",
    }
    std = aliases.get(key, key)
    if std in VERDICTS:
        return std
    return "NEEDS_REVIEW"


# ------------------------------------------------------------------------------
# Citation Fraud Statuses
# ------------------------------------------------------------------------------
CITATION_STATUSES = {
    "VERIFIED": {
        "label": "Verified Citation",
        "color": "#14B8A6",
        "icon": "🛡️",
        "desc": "DOI resolves successfully and paper metadata (title, authors, year) matches."
    },
    "DOI_NOT_FOUND": {
        "label": "DOI Not Found",
        "color": "#F97316",
        "icon": "🔍",
        "desc": "Specified DOI is not registered in official Crossref or scholarly registries."
    },
    "METADATA_MISMATCH": {
        "label": "Metadata Mismatch",
        "color": "#D6B56D",
        "icon": "⚠️",
        "desc": "DOI exists, but registered paper title, authors, or publication year conflict with citation."
    },
    "POSSIBLY_RETRACTED": {
        "label": "Possibly Retracted",
        "color": "#DC2626",
        "icon": "🚨",
        "desc": "Authoritative registry records indicate this paper has been retracted or flagged."
    },
    "UNVERIFIED": {
        "label": "Unverified",
        "color": "#64748B",
        "icon": "⏳",
        "desc": "Could not be automatically matched against external scholarly databases."
    },
    "NEEDS_MANUAL_REVIEW": {
        "label": "Needs Manual Review",
        "color": "#D97706",
        "icon": "👁️",
        "desc": "Ambiguous citation format or partial matching requiring human specialist audit."
    }
}

"""Configuration module for CiteVerify.
Loads environment variables, API endpoints, model parameters, and database paths.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Helper to read from environment or Streamlit Cloud st.secrets
def get_secret(key: str, default: str = "") -> str:
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

# Gemini AI Settings
GEMINI_API_KEY = (get_secret("GEMINI_API_KEY") or get_secret("LLM_API_KEY")).strip()
GEMINI_MODEL = get_secret("GEMINI_MODEL", "gemini-2.5-flash").strip()
DEFAULT_TEMPERATURE = float(get_secret("GEMINI_TEMPERATURE", "0.2"))

# Database settings
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "citeverify.db"))

# Scholarly API endpoints and settings
CROSSREF_API_URL = "https://api.crossref.org/works"
OPENALEX_API_URL = "https://api.openalex.org/works"
SEMANTIC_SCHOLAR_API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
PUBMED_ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "researcher@citeverify.org").strip()

# HTTP headers
USER_AGENT = f"CiteVerify/2.0 (mailto:{CONTACT_EMAIL}; Academic Verification Bot)"

# Processing limits
MAX_CLAIMS_DEFAULT = 25
REQUEST_TIMEOUT = 12  # seconds per HTTP call
OUTDATED_YEARS_THRESHOLD = 10

# Verdict Definitions and color codes
VERDICTS = {
    "SUPPORTED": {
        "label": "Supported",
        "color": "#10B981",
        "bg": "#ECFDF5",
        "icon": "✅",
        "desc": "The retrieved scientific evidence directly substantiates and corroborates the claim."
    },
    "PARTIALLY_SUPPORTED": {
        "label": "Partially Supported",
        "color": "#F59E0B",
        "bg": "#FFFBEB",
        "icon": "⚠️",
        "desc": "Evidence broadly aligns with the claim, but key conditions, sample limits, or scopes differ."
    },
    "REFUTED": {
        "label": "Refuted",
        "color": "#EF4444",
        "bg": "#FEF2F2",
        "icon": "❌",
        "desc": "Retrieved evidence directly contradicts, disproves, or mathematically invalidates the claim."
    },
    "CONTRADICTORY": {
        "label": "Contradictory",
        "color": "#8B5CF6",
        "bg": "#F5F3FF",
        "icon": "⚡",
        "desc": "Literature displays competing or inconclusive findings across independent peer-reviewed studies."
    },
    "NOT_ENOUGH_EVIDENCE": {
        "label": "Not Enough Evidence",
        "color": "#6B7280",
        "bg": "#F3F4F6",
        "icon": "❔",
        "desc": "Retrieved text lacks specific methodology or quantitative metrics to evaluate the claim."
    }
}

# Citation Fraud Statuses
CITATION_STATUSES = {
    "VERIFIED": {
        "label": "Verified Citation",
        "color": "#10B981",
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
        "color": "#EAB308",
        "icon": "⚠️",
        "desc": "DOI exists, but registered paper title, authors, or publication year conflict with the citation."
    },
    "POSSIBLY_RETRACTED": {
        "label": "Possibly Retracted",
        "color": "#DC2626",
        "icon": "🚨",
        "desc": "Authoritative registry records indicate this paper has been retracted or subjected to expression of concern."
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


def is_gemini_configured() -> bool:
    """Check if a Gemini API key is configured."""
    key = get_secret("GEMINI_API_KEY") or get_secret("LLM_API_KEY") or GEMINI_API_KEY
    return bool(key and len(key) > 5 and not key.startswith("your_"))

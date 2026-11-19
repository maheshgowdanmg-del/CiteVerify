"""Theme and UI styling module for CiteVerify.
Implements a premium Linear / Stripe / Vercel inspired SaaS design system:
- Dark navy sidebar (#0B132B, #0F172A)
- Clean light main workspace (#F8FAFC, #FFFFFF)
- Professional typography (Plus Jakarta Sans)
- Subtle blue accents (#2563EB, #38BDF8)
- Modern cards, pills, and metrics
"""
from __future__ import annotations

import html

CSS_STYLES = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {
    --bg-main: #F8FAFC;
    --card-bg: #FFFFFF;
    --sidebar-bg: #0F172A;
    --sidebar-card: #1E293B;
    --border-color: #E2E8F0;
    --accent-blue: #2563EB;
    --accent-light: #38BDF8;
    --text-primary: #0F172A;
    --text-muted: #64748B;
    --success: #10B981;
    --warning: #F59E0B;
    --danger: #EF4444;
}

/* Global Font & App Container */
html, body, [class*="css"], .stApp {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
    background-color: var(--bg-main);
    color: var(--text-primary);
}

.stApp {
    background: var(--bg-main);
}

/* Top App Header */
header[data-testid="stHeader"] {
    background: transparent;
}
#MainMenu, footer {
    visibility: hidden;
}

/* Sidebar Styling: Dark Navy */
[data-testid="stSidebar"] {
    background-color: var(--sidebar-bg) !important;
    border-right: 1px solid #1E293B !important;
}

[data-testid="stSidebar"] * {
    color: #F1F5F9 !important;
}

[data-testid="stSidebar"] hr {
    border-color: #334155 !important;
}

[data-testid="stSidebar"] .stSelectbox > div,
[data-testid="stSidebar"] .stMultiSelect > div,
[data-testid="stSidebar"] input {
    background-color: #1E293B !important;
    border-color: #334155 !important;
    color: #F8FAFC !important;
}

/* Brand Treatement */
.cv-brand {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 8px 0 16px;
    border-bottom: 1px solid #1E293B;
    margin-bottom: 16px;
}

.cv-brand-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: linear-gradient(135deg, #2563EB 0%, #38BDF8 100%);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.2rem;
    font-weight: 800;
    color: #FFFFFF;
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35);
}

.cv-brand-title {
    font-size: 1.15rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: #FFFFFF !important;
    line-height: 1.1;
}

.cv-brand-tagline {
    font-size: 0.72rem;
    color: #94A3B8 !important;
    font-weight: 500;
}

/* Premium Hero Container */
.cv-hero {
    background: #FFFFFF;
    border: 1px solid var(--border-color);
    border-radius: 16px;
    padding: 24px 28px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(15, 23, 42, 0.04);
    position: relative;
    overflow: hidden;
}

.cv-hero::after {
    content: "";
    position: absolute;
    top: 0;
    right: 0;
    width: 280px;
    height: 100%;
    background: radial-gradient(circle at top right, rgba(37, 99, 235, 0.08) 0%, transparent 70%);
    pointer-events: none;
}

.cv-hero-eyebrow {
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--accent-blue);
    margin-bottom: 6px;
}

.cv-hero-h1 {
    font-size: 1.9rem;
    font-weight: 800;
    color: var(--text-primary);
    margin: 0 0 8px 0;
    letter-spacing: -0.03em;
}

.cv-hero-p {
    font-size: 0.95rem;
    color: var(--text-muted);
    margin: 0;
    line-height: 1.5;
    max-width: 760px;
}

/* Metric Cards */
.cv-kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px;
    margin-bottom: 22px;
}

.cv-kpi-card {
    background: #FFFFFF;
    border: 1px solid var(--border-color);
    border-radius: 14px;
    padding: 16px 18px;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.cv-kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(15, 23, 42, 0.06);
}

.cv-kpi-val {
    font-size: 1.85rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: var(--text-primary);
    line-height: 1.1;
    margin-top: 6px;
}

.cv-kpi-label {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
}

.cv-kpi-sub {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 4px;
}

/* Custom Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: #F1F5F9;
    padding: 6px;
    border-radius: 12px;
    border: 1px solid var(--border-color);
}

.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 0.88rem;
    color: var(--text-muted);
    border: none !important;
}

.stTabs [aria-selected="true"] {
    background: #FFFFFF !important;
    color: var(--accent-blue) !important;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06);
}

/* Custom Buttons */
.stButton > button {
    border-radius: 10px !important;
    font-weight: 600 !important;
    font-size: 0.9rem !important;
    padding: 8px 20px !important;
    transition: all 0.15s ease-in-out !important;
}

.stButton > button[kind="primary"] {
    background: var(--accent-blue) !important;
    color: #FFFFFF !important;
    border: none !important;
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25) !important;
}

.stButton > button[kind="primary"]:hover {
    background: #1D4ED8 !important;
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(37, 99, 235, 0.35) !important;
}

/* Expanders */
[data-testid="stExpander"] {
    background: #FFFFFF !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 6px rgba(15, 23, 42, 0.02) !important;
    margin-bottom: 10px !important;
}

/* Modern Card Box */
.cv-card {
    background: #FFFFFF;
    border: 1px solid var(--border-color);
    border-radius: 14px;
    padding: 20px;
    box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03);
    margin-bottom: 18px;
}
</style>
"""


def inject_theme(st_instance) -> None:
    """Inject premium CSS styling into Streamlit app."""
    st_instance.markdown(CSS_STYLES, unsafe_allow_html=True)


def render_brand() -> str:
    """Render sidebar brand treatment."""
    return """
    <div class="cv-brand">
        <div class="cv-brand-icon">✓</div>
        <div>
            <div class="cv-brand-title">CiteVerify AI</div>
            <div class="cv-brand-tagline">Scientific Claim & Citation Intelligence</div>
        </div>
    </div>
    """


def render_hero(title: str, subtitle: str, description: str) -> str:
    """Render top hero banner."""
    return f"""
    <div class="cv-hero">
        <div class="cv-hero-eyebrow">{html.escape(subtitle)}</div>
        <h1 class="cv-hero-h1">{html.escape(title)}</h1>
        <p class="cv-hero-p">{html.escape(description)}</p>
    </div>
    """


def render_kpi_card(label: str, value: Any, subtext: str = "", border_color: str = "#2563EB") -> str:
    """Render a clean metric card."""
    return f"""
    <div class="cv-kpi-card" style="border-top: 3px solid {border_color};">
        <div class="cv-kpi-label">{html.escape(label)}</div>
        <div class="cv-kpi-val">{html.escape(str(value))}</div>
        <div class="cv-kpi-sub">{html.escape(subtext)}</div>
    </div>
    """

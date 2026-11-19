"""Premium dashboard theme: custom CSS, hero header, KPI cards, donut/bar charts (pure HTML/CSS, no extra deps).

All numbers shown by ``render_overview`` are computed from the real run; nothing is invented.
NOTE: HTML passed to st.markdown must not contain blank lines or 4+ leading spaces (Markdown would treat it as code),
so every builder returns a single compact string.
"""
from __future__ import annotations

import html

from src import insights

NAVY, PANEL, GOLD, TEAL = "#0B1220", "#111B2E", "#D6B56D", "#14B8A6"
LABEL_COLORS = {"Supported": "#22c55e", "Partially Supported": "#f59e0b", "Unsupported": "#ef4444",
                "Contradictory": "#a855f7", "Needs Review": "#94a3b8"}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--navy:#0B1220;--panel:#111B2E;--panel2:#16223A;--border:#22304D;--gold:#D6B56D;--teal:#14B8A6;--text:#E6EAF2;--muted:#9AA7BF;}
html, body, .stApp, [class*="st-"]{font-family:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;}
.stApp{background:radial-gradient(1100px 480px at 8% -8%,rgba(20,184,166,.10),transparent 60%),radial-gradient(900px 420px at 100% 0%,rgba(214,181,109,.10),transparent 55%),#0B1220;color:var(--text);}
header[data-testid="stHeader"]{background:transparent;}
#MainMenu, footer{visibility:hidden;}
.block-container{padding-top:1.3rem;max-width:1280px;}
[data-testid="stSidebar"]{background:#0D1627;border-right:1px solid var(--border);}
h1,h2,h3{letter-spacing:-.01em;}
.cv-hero{border:1px solid var(--border);border-radius:20px;padding:28px 32px;background:linear-gradient(135deg,#14213C 0%,#0F1A2F 65%);position:relative;overflow:hidden;margin-bottom:18px;}
.cv-hero:after{content:"";position:absolute;right:-70px;top:-70px;width:240px;height:240px;border-radius:50%;background:radial-gradient(circle,rgba(214,181,109,.28),transparent 70%);}
.cv-eyebrow{color:var(--gold);letter-spacing:.16em;font-size:.72rem;font-weight:700;text-transform:uppercase;}
.cv-hero h1{font-size:2.2rem;font-weight:800;margin:.25rem 0 .3rem;padding:0;color:#fff;}
.cv-hero p{color:var(--muted);margin:0;font-size:1rem;max-width:760px;}
.cv-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;}
.cv-chip{border:1px solid var(--border);background:rgba(255,255,255,.04);color:var(--text);border-radius:999px;padding:4px 12px;font-size:.78rem;font-weight:500;}
.cv-chip b{color:var(--gold);font-weight:700;margin-right:4px;}
.cv-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px;margin:6px 0 18px;}
.cv-kpi{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:16px 18px;transition:transform .15s,border-color .15s,box-shadow .15s;}
.cv-kpi:hover{transform:translateY(-2px);border-color:var(--accent,#D6B56D);box-shadow:0 10px 26px rgba(0,0,0,.35);}
.cv-kpi .ic{font-size:1.15rem;width:36px;height:36px;display:grid;place-items:center;border-radius:10px;background:rgba(255,255,255,.06);}
.cv-kpi .v{font-size:1.95rem;font-weight:800;color:#fff;line-height:1.1;margin-top:10px;}
.cv-kpi .v small{font-size:.9rem;color:var(--muted);font-weight:600;}
.cv-kpi .l{color:var(--text);font-weight:600;font-size:.86rem;margin-top:3px;}
.cv-kpi .h{color:var(--muted);font-size:.76rem;margin-top:2px;}
.cv-card{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:18px 20px;height:100%;}
.cv-card h4{margin:0 0 4px;font-size:1rem;font-weight:700;color:#fff;}
.cv-card .sub{color:var(--muted);font-size:.78rem;margin-bottom:14px;}
.cv-donut-wrap{display:flex;align-items:center;gap:22px;flex-wrap:wrap;}
.cv-donut{width:150px;height:150px;border-radius:50%;position:relative;flex:0 0 auto;}
.cv-donut:after{content:"";position:absolute;inset:24px;background:var(--panel);border-radius:50%;}
.cv-donut .c{position:absolute;inset:0;display:grid;place-items:center;z-index:1;text-align:center;}
.cv-donut .c b{font-size:1.5rem;color:#fff;display:block;line-height:1;}
.cv-donut .c span{font-size:.68rem;color:var(--muted);}
.cv-legend div{display:flex;align-items:center;gap:8px;font-size:.82rem;margin:4px 0;color:var(--text);}
.cv-legend i{width:10px;height:10px;border-radius:3px;display:inline-block;}
.cv-legend em{color:var(--muted);font-style:normal;margin-left:auto;padding-left:14px;}
.cv-bar{margin:9px 0;}
.cv-bar .t{display:flex;justify-content:space-between;font-size:.8rem;color:var(--text);margin-bottom:4px;}
.cv-bar .t em{color:var(--muted);font-style:normal;}
.cv-bar .tr{height:8px;border-radius:999px;background:rgba(255,255,255,.07);overflow:hidden;}
.cv-bar .f{height:100%;border-radius:999px;}
.cv-steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px;margin:6px 0 16px;}
.cv-step{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:18px;}
.cv-step .n{color:var(--gold);font-weight:800;font-size:.8rem;letter-spacing:.12em;}
.cv-step h4{margin:.3rem 0;color:#fff;font-size:1.02rem;}
.cv-step p{margin:0;color:var(--muted);font-size:.85rem;}
.cv-pill{display:inline-block;padding:3px 12px;border-radius:999px;font-size:.78rem;font-weight:600;color:#fff;}
.stTabs [data-baseweb="tab-list"]{gap:6px;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.stTabs [data-baseweb="tab"]{height:auto;padding:9px 16px;border-radius:10px 10px 0 0;color:var(--muted);font-weight:600;}
.stTabs [aria-selected="true"]{color:var(--gold)!important;background:rgba(214,181,109,.08);}
.stTabs [data-baseweb="tab-highlight"]{background:var(--gold)!important;}
.stButton>button,.stDownloadButton>button{border-radius:12px;border:1px solid var(--border);background:var(--panel2);color:var(--text);font-weight:600;transition:all .15s;}
.stButton>button:hover,.stDownloadButton>button:hover{border-color:var(--gold);color:var(--gold);transform:translateY(-1px);}
.stButton>button[kind="primary"],[data-testid="stBaseButton-primary"]{background:var(--gold)!important;color:#0B1220!important;border:none!important;}
.stButton>button[kind="primary"]:hover,[data-testid="stBaseButton-primary"]:hover{background:#E6CB8C!important;color:#0B1220!important;}
[data-testid="stExpander"]{border:1px solid var(--border)!important;border-radius:14px!important;background:var(--panel);}
[data-testid="stFileUploaderDropzone"]{background:var(--panel);border:2px dashed #2B3B5E;border-radius:16px;transition:border-color .15s;}
[data-testid="stFileUploaderDropzone"]:hover{border-color:var(--gold);}
[data-testid="stMetric"]{background:var(--panel);border:1px solid var(--border);border-radius:14px;padding:12px 16px;}
[data-testid="stDataFrame"]{border:1px solid var(--border);border-radius:12px;overflow:hidden;}
.stProgress>div>div>div>div{background:linear-gradient(90deg,#14B8A6,#D6B56D);}
mark{background:rgba(214,181,109,.35);color:#fff;border-radius:3px;padding:0 2px;}
@media (max-width:640px){.cv-hero{padding:20px;}.cv-hero h1{font-size:1.55rem;}.block-container{padding:1rem .8rem;}.cv-donut-wrap{justify-content:center;}}
</style>
"""


def inject(st) -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def hero(title: str, eyebrow: str, subtitle: str, chips: list[tuple[str, str]] | None = None) -> str:
    chip_html = "".join(f'<span class="cv-chip"><b>{esc(a)}</b>{esc(b)}</span>' for a, b in (chips or []))
    return (f'<div class="cv-hero"><div class="cv-eyebrow">{esc(eyebrow)}</div><h1>{esc(title)}</h1>'
            f'<p>{esc(subtitle)}</p>' + (f'<div class="cv-chips">{chip_html}</div>' if chip_html else "") + "</div>")


def kpi_grid(items: list[dict]) -> str:
    cards = []
    for it in items:
        suffix = f"<small> {esc(it['suffix'])}</small>" if it.get("suffix") else ""
        cards.append(f'<div class="cv-kpi" style="--accent:{it.get("color", GOLD)}"><div class="ic">{it.get("icon", "")}</div>'
                     f'<div class="v">{esc(it["value"])}{suffix}</div><div class="l">{esc(it["label"])}</div>'
                     f'<div class="h">{esc(it.get("hint", ""))}</div></div>')
    return '<div class="cv-grid">' + "".join(cards) + "</div>"


def donut(counts: dict, colors: dict, center_label: str = "claims") -> str:
    total = sum(counts.values())
    if total:
        stops, acc = [], 0.0
        for k, v in counts.items():
            if not v:
                continue
            start, acc = acc, acc + 100.0 * v / total
            stops.append(f"{colors.get(k, '#94a3b8')} {start:.2f}% {acc:.2f}%")
        ring = ", ".join(stops)
    else:
        ring = "#22304D 0% 100%"
    legend = "".join(f'<div><i style="background:{colors.get(k, "#94a3b8")}"></i>{esc(k)}<em>{v}</em></div>' for k, v in counts.items())
    return (f'<div class="cv-donut-wrap"><div class="cv-donut" style="background:conic-gradient({ring})">'
            f'<div class="c"><div><b>{total}</b><span>{esc(center_label)}</span></div></div></div>'
            f'<div class="cv-legend">{legend}</div></div>')


def bars(rows: list[tuple[str, float, str]], total: float | None = None, color: str = TEAL) -> str:
    """rows = (label, value, display_text); bar width = value / total (or max)."""
    base = total if total else (max((v for _, v, _ in rows), default=0) or 1)
    out = []
    for label, value, shown in rows:
        pct = max(0.0, min(100.0, 100.0 * value / base)) if base else 0.0
        out.append(f'<div class="cv-bar"><div class="t"><span>{esc(label)}</span><em>{esc(shown)}</em></div>'
                   f'<div class="tr"><div class="f" style="width:{pct:.1f}%;background:{color}"></div></div></div>')
    return "".join(out)


def card(title: str, subtitle: str, body: str) -> str:
    return f'<div class="cv-card"><h4>{esc(title)}</h4><div class="sub">{esc(subtitle)}</div>{body}</div>'


def pill(name: str, color: str) -> str:
    return f'<span class="cv-pill" style="background:{color}">{esc(name)}</span>'


def welcome_steps() -> str:
    steps = [("01", "Upload", "Drop a PDF, DOCX or TXT paper - or try the built-in sample with planted errors."),
             ("02", "Verify", "CiteVerify finds claims and citations, retrieves the original papers and compares the evidence."),
             ("03", "Review", "Inspect verdicts, evidence quotes and source links, get better source suggestions, export the report.")]
    return '<div class="cv-steps">' + "".join(
        f'<div class="cv-step"><div class="n">STEP {n}</div><h4>{esc(t)}</h4><p>{esc(d)}</p></div>' for n, t, d in steps) + "</div>"


def confidence_bins(results: list) -> list[tuple[str, int]]:
    edges = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    counts = [0] * len(edges)
    for r in results:
        c = float((r.get("confidence") or {}).get("score") or 0)
        for i, (lo, hi) in enumerate(edges):
            if lo <= c < hi:
                counts[i] += 1
                break
    return [(f"{lo:.1f} - {min(hi, 1.0):.1f}", n) for (lo, hi), n in zip(edges, counts)]


def render_overview(st, run: dict, results: list, summary: dict, *, n_documents: int, mode: str,
                    outdated_years: int = 10) -> None:
    """KPI cards + donut + confidence + reference funnel, all computed from the actual run."""
    classes = [insights.classify_status(r.get("final_status")) for r in results]
    ts = insights.trust_score(run, results)
    health = insights.reference_health(run, results, outdated_years=outdated_years)["funnel"]
    kpis = [
        {"icon": "📄", "value": n_documents, "label": "Documents verified", "hint": "saved runs in history", "color": TEAL},
        {"icon": "🧾", "value": summary.get("total_findings", len(results)), "label": "Claims analysed", "hint": "in this document", "color": GOLD},
        {"icon": "✅", "value": classes.count("supported"), "label": "Supported", "hint": "source backs the claim", "color": LABEL_COLORS["Supported"]},
        {"icon": "⛔", "value": classes.count("unsupported") + classes.count("contradictory"), "label": "Unsupported / contradictory",
         "hint": "source does not back it", "color": LABEL_COLORS["Unsupported"]},
        {"icon": "🔍", "value": summary.get("needs_review", 0), "label": "Needs review", "hint": "human decision required", "color": LABEL_COLORS["Partially Supported"]},
        {"icon": "🛡️", "value": "n/a" if ts["score"] is None else ts["score"], "suffix": "" if ts["score"] is None else "/100",
         "label": "CiteVerify Trust Score", "hint": ts["grade"] + " - transparent heuristic", "color": GOLD},
    ]
    st.markdown(kpi_grid(kpis), unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    dist = insights.official_distribution(results)
    c1.markdown(card("Claim verdicts", "The five official labels", donut(dist, LABEL_COLORS)), unsafe_allow_html=True)
    cb = confidence_bins(results)
    c2.markdown(card("Confidence distribution", "Evidence strength, not a guarantee",
                     bars([(a, n, str(n)) for a, n in cb], total=max(1, len(results)), color=GOLD)), unsafe_allow_html=True)
    total_refs = max(1, health["references"])
    c3.markdown(card("Citation integrity", "A real paper is not proof of a claim",
                     bars([("References", health["references"], str(health["references"])),
                           ("Verified to exist", health["exist"], str(health["exist"])),
                           ("Matched to a claim", health["matched_to_claim"], str(health["matched_to_claim"])),
                           ("Support a claim", health["support_a_claim"], str(health["support_a_claim"]))],
                          total=total_refs, color=TEAL)), unsafe_allow_html=True)
    st.markdown(f'<div class="cv-chips" style="margin-top:14px"><span class="cv-chip"><b>Mode</b>{esc(mode)}</span>'
                f'<span class="cv-chip"><b>References resolved</b>{esc(summary.get("references_resolved", 0))}/{esc(summary.get("references_total", 0))}</span>'
                f'<span class="cv-chip"><b>Avg confidence</b>{esc(summary.get("avg_confidence") if summary.get("avg_confidence") is not None else "n/a")}</span>'
                f'<span class="cv-chip"><b>Source access</b>{esc(summary.get("source_access", "n/a"))}</span></div>', unsafe_allow_html=True)

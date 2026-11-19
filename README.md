# 🔎 CiteVerify – Scientific Claim and Citation Verification System

> Upload a research paper → CiteVerify finds every claim and citation, retrieves the **original cited papers**, checks whether each source **really supports** the statement, and produces an **evidence-backed report** – with confidence scores and human review on every finding.

**Live demo:** _add your Streamlit link_ · **Demo video:** _add your link_ · **Hackathon:** InnovEdge 2026 – Problem Statement 03

---

## 1. The problem
A reference can be incorrect, outdated, retracted, unrelated – or a genuine paper that simply **does not prove the claim** (for example, the claim says "improved scores by 30%" but the paper reports a small pilot with no 30% figure). Checking every reference manually is slow, so unsupported statements slip through.

## 2. How it works (pipeline)
```
Upload PDF/DOCX/TXT
   → Extract text and split body / reference list              (src/extract.py)
   → Detect claims + citations  [1], [1-3], (Author, Year)     (src/claims.py)
   → Parse references (title, year, DOI, arXiv id) and map     (src/claims.py)
   → Retrieve original paper: Crossref, OpenAlex,
     Semantic Scholar, arXiv, Unpaywall (open-access PDF)      (src/retrieval.py)
   → Find best-matching evidence passages (TF-IDF [+embeddings]
     + number matching), with section/page                     (src/matching.py)
   → LLM judges claim vs. evidence → verdict + exact quote  (src/verdict.py)
   → Quote verification, numeric check, confidence breakdown   (src/verdict.py)
   → Report + human review + audit trail + export              (app.py, src/report.py)
```

## 3. Features vs. the problem statement
| Requirement (Problem Statement 03) | How CiteVerify implements it | Code |
|---|---|---|
| Upload a research paper/document | PDF, DOCX and TXT upload (plus a built-in sample) | `app.py`, `src/extract.py` |
| Find statements, facts, numbers, conclusions needing evidence | Sentence-level claim extraction using citations **and** claim cues (percentages, "studies show", "significantly"…) | `src/claims.py` |
| Citation detection `[1]`, `(Author, Year)` + reference list | Regex detection incl. ranges `[2-4]`, multi-cites `(A, 2019; B, 2020)`; reference-list parser | `src/claims.py` |
| Match each claim to the correct reference | Numeric-id and author-year mapping; unmatched citations flagged | `map_citation()` |
| Original paper retrieval (title, author, DOI) | DOI → Crossref/OpenAlex/Semantic Scholar; arXiv id; title search fallback with similarity threshold; Unpaywall for open-access PDFs | `src/retrieval.py` |
| Evidence comparison (findings, scope, limitations) | Top-k passages sent to a free LLM (Groq / Gemini / Ollama), which checks numbers, sample size, causality and generalisation | `src/verdict.py` |
| Status classification | Supported · Partly supported · Unsupported · Contradictory · Possibly outdated (+ Cannot verify, Missing citation, Bad reference) | `STATUS` in `src/verdict.py` |
| Misleading reference detection | Reference not found, DOI invalid, citation not in list, **retracted** paper, unrelated source, numeric mismatch, scope issues | flags in `verify_claim()` |
| Evidence & source traceability | Highlighted passage, section/page, source link, providers used | UI "Source trace" |
| Verification report with confidence and human review list | PDF / HTML / JSON / CSV export; "Needs human review" tab | `src/report.py` |
| Confidence = strength + uncertainty, not a guarantee | Transparent weighted breakdown (retrieval similarity, source access, number agreement, model certainty, quote verified, reference match) | `compute_confidence()` |
| Review history | Accept / override / comment per finding, stored with timestamps in SQLite | `src/storage.py` |

### Extras that build trust
* **Quote verification** – the evidence quote returned by the LLM must exist in the retrieved source text; otherwise it is flagged `quote_unverified` and confidence is capped. This blocks hallucinated evidence.
* **Numeric claim checker** – catches "30%" vs. what the paper actually reports.
* **Retraction check** – via Crossref and OpenAlex metadata.
* **Honest "Cannot verify"** when only metadata/abstract is available (paywalled papers); abstract-only results get lower confidence.
* **Caching** of every API/LLM call → reproducible, fast, cheap.
* **Offline rule-based mode** when no LLM is configured (confidence capped at 0.5).

## 4. Quick start
```bash
git clone https://github.com/YOUR_USERNAME/CiteVerify.git
cd CiteVerify
python -m venv .venv
# Windows: .venv\Scripts\activate      Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env  -> then add your keys
streamlit run app.py
```
Open http://localhost:8501, click **Use sample document**, then **Verify claims**.

### API keys (.env) - everything is free
| Variable | Required? | Where to get it |
|---|---|---|
| `LLM_PROVIDER` + `LLM_API_KEY` | Recommended | **Groq**: console.groq.com (free) - or **Gemini**: aistudio.google.com/apikey (free) - or **Ollama** (local, no key) |
| `CONTACT_EMAIL` | Yes (polite-pool access for Crossref/OpenAlex/Unpaywall) | your real email |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional | semanticscholar.org/product/api |
Crossref, OpenAlex, arXiv and Unpaywall need no key. With `LLM_PROVIDER=none` the app still works in rule-based mode.

## 5. Tests and benchmark
```bash
pytest                         # unit + end-to-end tests (network mocked)
python -m scripts.benchmark    # accuracy on the planted-error sample document
```
Results are written to `docs/benchmark_results.md`.

**Benchmark results:** _paste your numbers here after running the benchmark (e.g. "6/7 = 86%")._

The sample document contains planted problems: a correct claim, an inflated number (45.0 vs 28.4 BLEU), an over-generalised claim, a **retracted** paper, a **fabricated** reference and an **uncited** claim.

## 6. Trust, ethics and limitations
* Results are **decision support, not final academic judgments** – every finding is reviewable and overridable; all human decisions are logged.
* Full-text evidence is only available for open-access papers; otherwise the tool says so and lowers confidence.
* Reference parsing uses heuristics and may fail on unusual citation styles.
* LLM verdicts can be wrong; quote verification and the numeric check reduce, but do not remove, this risk.
* Retraction detection depends on the metadata of Crossref/OpenAlex.
* Scanned PDFs without a text layer are not supported (no OCR).

## 7. Tech stack
Python · Streamlit · free LLM APIs (Groq / Google Gemini / local Ollama) · Crossref · OpenAlex · Semantic Scholar · arXiv · Unpaywall · scikit-learn · PyMuPDF · python-docx · SQLite · ReportLab · pytest

## 8. Project structure
```
CiteVerify/
├── app.py                 # Streamlit web UI
├── src/
│   ├── config.py          # settings from .env
│   ├── extract.py         # PDF/DOCX/TXT reading
│   ├── claims.py          # claims, citations, reference parsing
│   ├── retrieval.py       # Crossref/OpenAlex/S2/arXiv/Unpaywall
│   ├── matching.py        # evidence passage ranking
│   ├── verdict.py         # LLM judge, quote check, confidence
│   ├── pipeline.py        # end-to-end orchestration
│   ├── report.py          # PDF/HTML/JSON/CSV export
│   └── storage.py         # SQLite cache, runs, review history
├── tests/  scripts/  data/sample/  docs/
├── requirements.txt  .env.example  .gitignore  LICENSE
```

## 9. Future work
OCR for scanned PDFs · publisher full-text APIs · citation-context analysis for whole reference lists · multilingual documents · browser extension.

## 10. Team
_Add names and roles._ · License: MIT

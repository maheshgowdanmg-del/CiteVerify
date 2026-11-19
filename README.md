# 🔎 CiteVerify AI – Scientific Claim & Citation Verification System

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Streamlit App](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)](https://streamlit.io/)
[![Google GenAI](https://img.shields.io/badge/AI-Google%20Gemini-4285F4.svg)](https://ai.google.dev/)
[![Scholarly APIs](https://img.shields.io/badge/Data-Crossref%20%7C%20OpenAlex%20%7C%20PubMed-green.svg)](https://crossref.org)
[![Tests Passing](https://img.shields.io/badge/tests-16%20passed-success.svg)](tests/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Central Principle:** *A citation is not proof by itself.*  
> Checking whether a research paper exists in a database only tells you that a title was registered. CiteVerify answers the real academic question: **Does that research paper actually support the specific scientific claim and quantitative measurements made?**

---

## 🌟 Key Capabilities

1. **Multi-Format Ingestion**: Upload academic manuscripts in **PDF**, **DOCX**, or **TXT**. Automatically splits body text from bibliographies and detects reference markers (`[1]`, `(Author, Year)`).
2. **Gemini AI Scientific Claim Extraction**: Employs Google Gemini with structured JSON Schema to identify empirical findings, diagnostic benchmarks, numerical metrics, and topics.
3. **Citation Fraud Detection Engine**:
   - Crossref & OpenAlex registry verification.
   - Detects fabricated DOIs (`DOI_NOT_FOUND`).
   - Unmasks hijacked DOIs and citation mismatch (`METADATA_MISMATCH`).
   - Flags retracted research papers and formal concerns (`POSSIBLY_RETRACTED`).
4. **Original Research Evidence Retrieval**:
   - Live querying across Crossref, OpenAlex, Semantic Scholar, and PubMed.
   - Retrieves full publication metadata, abstracts, and open-access links.
5. **Exact Numerical Claim Auditing**:
   - Special audit algorithms for percentages, sample sizes ($n$), accuracy metrics, and hazard ratios.
   - Pinpoints exact numeric distortions (e.g., Claim asserts $45\%$ improvement; Evidence reports $28.4\%$).
6. **5-Category Gemini Verification Engine**:
   - `SUPPORTED`: Paper directly substantiates the claim.
   - `PARTIALLY_SUPPORTED`: General findings align, but scope or conditions differ.
   - `REFUTED`: Evidence actively disproves or negates the claim.
   - `CONTRADICTORY`: Opposing literature or conflicting peer-reviewed trials exist.
   - `NOT_ENOUGH_EVIDENCE`: Open abstracts lack specific methodology to verify.
7. **Contradiction Intelligence**: Multi-study comparative synthesis identifying supporting vs. opposing trials, methodological differences, and scanner drifts.
8. **Interactive Citation Trust Graph**: Color-coded Plotly network visualizing relationships between documents, claims, verified evidence, and fraud alerts.
9. **Academic Trust Score (0–100)**: Transparent weighted score combining claim corroboration ($40\%$), citation validity ($25\%$), evidence coverage ($20\%$), and fraud/retraction penalties ($15\%$).
10. **Human Review & Audit Trail**: Reviewer controls allowing users to accept AI verdicts, override decisions, and record timestamped comments stored in SQLite.
11. **Authoritative Research Recommender**: Queries OpenAlex and Semantic Scholar to recommend reputable peer-reviewed sources for unsupported claims.
12. **Multi-Format Verification Reports**: Instant downloadable **PDF** (styled ReportLab report with KPI metrics), **JSON** (complete data archive with audit trail), and **CSV** (tabular spreadsheet).

---

## 🏗️ Architecture & Directory Structure

```
CiteVerify/
│
├── app.py                         # Main Streamlit application & navigation router
├── requirements.txt               # Production Python dependencies
├── README.md                      # Complete system documentation & deployment guide
├── .env.example                   # Template for API credentials
├── .gitignore                     # Git exclusions
│
├── src/
│   ├── config.py                  # Environment config, API endpoints & verdict styles
│   ├── database.py                # SQLite database schema, CRUD & analytical queries
│   ├── pdf_extractor.py           # Multi-format document parser (PDF, DOCX, TXT)
│   ├── claim_extractor.py         # Gemini AI scientific claim extractor + heuristic fallback
│   ├── citation_parser.py         # In-text marker & bibliography reference parser
│   ├── citation_checker.py        # Crossref citation fraud & retraction engine
│   ├── research_retriever.py      # Crossref, OpenAlex, Semantic Scholar & PubMed client
│   ├── evidence_matcher.py        # Passage extractor & numerical verification auditor
│   ├── gemini_engine.py           # Core 5-category Gemini claim verification engine
│   ├── contradiction_detector.py  # Cross-study contradiction & consensus analyzer
│   ├── trust_score.py             # Transparent 0-100 Academic Trust Score calculator
│   ├── report_generator.py        # ReportLab PDF, JSON & CSV export engine
│   ├── graph_builder.py           # Interactive Plotly Citation Trust Graph generator
│   ├── theme.py                   # Premium Linear/Stripe/Vercel SaaS design system
│   └── utils.py                   # Text normalization, fuzzy matching & HTML utilities
│
├── pages/                         # Multi-page modular router views
│   ├── dashboard.py
│   ├── document_analysis.py
│   ├── citation_fraud.py
│   ├── evidence_comparison.py
│   ├── research_intelligence.py
│   └── reports.py
│
├── assets/
│   ├── logo.png                   # Custom CiteVerify brand treatment
│   └── dashboard_preview.png      # Application visual preview
│
├── data/
│   └── sample/
│       ├── sample_paper.txt       # Realistic oncology manuscript with verified & fraudulent citations
│       ├── sample_paper.pdf       # Formatted PDF test manuscript
│       └── sample_paper.docx      # Formatted DOCX test manuscript
│
└── tests/
    ├── test_extraction.py         # PDF/DOCX/TXT and reference splitting tests
    ├── test_citations.py          # DOI validation, metadata matching & fraud tests
    └── test_verification.py       # Numerical verification, trust score, SQLite & report tests
```

---

## 🚀 Quick Start Guide

### 1. Clone or Open Project
```bash
cd CiteVerify
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Gemini AI API Key
Create a `.env` file from the example:
```bash
cp .env.example .env
```
Add your free Google Gemini API key (obtain from [Google AI Studio](https://aistudio.google.com/)):
```ini
GEMINI_API_KEY=AIzaSy...your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```

> **Note:** CiteVerify includes a built-in offline rule engine. If no Gemini API key is configured, the application functions seamlessly in offline demonstration mode!

### 4. Run the Application
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 🧪 Running Automated Tests

CiteVerify comes with a comprehensive, automated test suite:
```bash
python -m pytest tests/ -v
```
All 16 tests cover text extraction, reference parsing, DOI validation, numerical verification, trust scoring, SQLite operations, and PDF generation.

---

## 📊 Evaluation Criteria & Transparent Trust Score Formula

The **CiteVerify Academic Trust Score** ($0 \le S \le 100$) is computed transparently:

$$\text{Score} = 0.40 \cdot C_{\text{support}} + 0.25 \cdot I_{\text{citation}} + 0.20 \cdot E_{\text{coverage}} + 0.15 \cdot P_{\text{integrity}}$$

Where:
- **$C_{\text{support}}$ (Claim Verification Quality):** Average support credit across audited claims ($1.0$ for `SUPPORTED`, $0.6$ for `PARTIALLY_SUPPORTED`, $0.25$ for `CONTRADICTORY`, $0.0$ for `REFUTED`, $0.35$ for `NOT_ENOUGH_EVIDENCE`).
- **$I_{\text{citation}}$ (Citation & DOI Validity):** Percentage of bibliographic citations successfully verified against registry records.
- **$E_{\text{coverage}}$ (Evidence Coverage):** Percentage of claims with verbatim retrieved evidence excerpts.
- **$P_{\text{integrity}}$ (Absence of Fraud Penalties):** Base $100$ points with explicit deductions:
  - $-25$ pts per retracted or flagged publication.
  - $-15$ pts per fabricated/unregistered DOI.
  - $-10$ pts per citation metadata mismatch.
  - $-12$ pts per quantitative numerical distortion.

---

## ☁️ Deployment on Streamlit Community Cloud

1. Push this repository to GitHub.
2. Visit [share.streamlit.io](https://share.streamlit.io).
3. Connect your repository and specify `app.py` as the main file path.
4. In **Advanced Settings & Secrets**, add:
   ```toml
   GEMINI_API_KEY = "your_key_here"
   GEMINI_MODEL = "gemini-2.5-flash"
   ```
5. Deploy!

---

## 🔒 Security & Privacy

- **No Hardcoded Credentials**: API credentials load exclusively from environment variables or secure session state.
- **Local SQLite Storage**: Manuscripts and verification records are stored locally on your machine.
- **Open Scholarly Standards**: All retrieval calls use standard Crossref, OpenAlex, Semantic Scholar, and NCBI PubMed public REST APIs respecting `User-Agent` and rate limit etiquette.

---

## 📜 Academic Integrity Disclaimer

CiteVerify AI is designed as research intelligence and integrity decision support. Automated models evaluate statements against available open scientific abstracts and indices; they do not replace formal peer review or authorized journal editorial evaluation.

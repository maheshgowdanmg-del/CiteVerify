# PROJECT_NOTES (paste this at the start of a new Claude chat to save tokens)
Project: CiteVerify - Streamlit app that verifies whether cited papers support claims.
Stack: Python 3.10+, Streamlit, free OpenAI-compatible LLM (Groq/Gemini/Ollama), Crossref/OpenAlex/Semantic Scholar/arXiv/Unpaywall, SQLite, scikit-learn, reportlab.
Flow: src/extract.py -> src/claims.py -> src/retrieval.py -> src/matching.py -> src/verdict.py -> src/pipeline.py -> src/report.py; UI in app.py.
Done: all modules, tests (tests/), benchmark (scripts/benchmark.py), sample doc (data/sample).
TODO: record demo video, paste benchmark numbers into README, deploy to Streamlit Community Cloud.

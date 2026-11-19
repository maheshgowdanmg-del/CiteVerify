@echo off
cd /d "%~dp0"
echo Starting CiteVerify AI...
call .venv\Scripts\activate.bat
streamlit run app.py
pause

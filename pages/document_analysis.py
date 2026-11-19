"""CiteVerify - Document Analysis & Extraction (Multi-page)."""
import streamlit as st

if "selected_page" in st.session_state:
    st.session_state.selected_page = "Document Analysis"

st.info("Please navigate using the primary CiteVerify sidebar on the main app.")
if st.button("Go to Document Analysis in Main App"):
    st.switch_page("app.py")

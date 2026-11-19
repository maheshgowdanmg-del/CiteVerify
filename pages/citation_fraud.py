"""CiteVerify - Citation Fraud Detection (Multi-page)."""
import streamlit as st

st.session_state.selected_page = "Citation Fraud Detection"
st.info("Please navigate using the primary CiteVerify sidebar on the main app.")
if st.button("Go to Citation Fraud in Main App"):
    st.switch_page("app.py")

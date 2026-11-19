"""CiteVerify - Evidence Comparison (Multi-page)."""
import streamlit as st

st.session_state.selected_page = "Evidence Comparison"
st.info("Please navigate using the primary CiteVerify sidebar on the main app.")
if st.button("Go to Evidence Comparison in Main App"):
    st.switch_page("app.py")

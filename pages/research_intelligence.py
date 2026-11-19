"""CiteVerify - Research Intelligence & Contradiction Analysis (Multi-page)."""
import streamlit as st

st.session_state.selected_page = "Contradiction Intelligence"
st.info("Please navigate using the primary CiteVerify sidebar on the main app.")
if st.button("Go to Research Intelligence in Main App"):
    st.switch_page("app.py")

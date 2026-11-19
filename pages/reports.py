"""CiteVerify - Verification Reports (Multi-page)."""
import streamlit as st

st.session_state.selected_page = "Verification Reports"
st.info("Please navigate using the primary CiteVerify sidebar on the main app.")
if st.button("Go to Verification Reports in Main App"):
    st.switch_page("app.py")

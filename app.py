"""
app.py - RSS Relay Explorer (fetch layer) Streamlit GUI entry point

Usage:
    streamlit run app.py
"""

from pathlib import Path
import sys

# Add rss/ to path so core / ui can be imported directly
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
from ui import feed_tab

st.set_page_config(page_title="RSS Relay Explorer", page_icon="📡", layout="wide")


def main():
    st.title("RSS Relay Explorer")
    feed_tab.render()


if __name__ == "__main__":
    main()

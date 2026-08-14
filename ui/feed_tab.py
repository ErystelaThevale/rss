"""
ui/feed_tab.py - Fetch tab

- Days-back input + fetch button pulls newest items from HN/Reddit/Lemmy and
  translates + saves titles
- Before a run (or when the button hasn't been pressed), the saved CSV is
  loaded and shown instead
"""

import streamlit as st

from core import DEFAULT_DAYS_BACK, DEEPL_TOKEN, REDDIT_MAX_PER_SUBREDDIT, run_acquisition, load_saved_items


def render():
    st.header("Fetch")

    col1, col2, col3, col4 = st.columns([1, 1, 1, 2])
    with col1:
        days_back = st.number_input(
            "Days back", min_value=1, max_value=90, value=DEFAULT_DAYS_BACK
        )
    with col2:
        translate = st.checkbox(
            "Translate titles",
            value=bool(DEEPL_TOKEN),
            help="DeepLでタイトルを翻訳する。DEEPL_TOKEN未設定でも、チェックを外せば翻訳なしで動作する",
        )
    with col3:
        reddit_cap = st.number_input(
            "Reddit: max/sub",
            min_value=1, max_value=100, value=REDDIT_MAX_PER_SUBREDDIT,
            help="Reddit結合フィードで、1サブレディットあたり最大何件まで残すか（活発なサブレが枠を独占しないための上限）",
        )
    with col4:
        st.write("")
        run = st.button("Fetch", type="primary")

    if run:
        spinner_text = "Fetching and translating…" if translate else "Fetching…"
        with st.spinner(spinner_text):
            try:
                df = run_acquisition(
                    days_back=int(days_back),
                    translate=translate,
                    reddit_max_per_subreddit=int(reddit_cap),
                )
            except Exception as e:
                st.error(f"Fetch failed: {e}")
                df = None
        if df is not None:
            st.session_state["rss_items"] = df
            st.success(f"Done: {len(df)} items")

    st.divider()

    df = st.session_state.get("rss_items")
    if df is None:
        df = load_saved_items()

    if df is None or df.empty:
        st.info("No items yet. Press \"Fetch\" to get started.")
        return

    st.caption(f"{len(df)} items")
    # reindexで欠けている列はNaN補完（保存済みCSVが古いスキーマのままでもKeyErrorにしない。
    # 2026-08-14に列名不整合でクラッシュした実例を踏まえた対策。DESIGN_NOTES.md §3参照）
    display_columns = ["source", "comments", "title_translated", "published_at", "link"]
    st.dataframe(
        df.reindex(columns=display_columns),
        width="stretch",
        height=600,
        hide_index=True,
        column_config={
            "source": st.column_config.TextColumn("Source"),
            "comments": st.column_config.NumberColumn("Comments", help="現在のコメント数（活性度の指標）。Redditは未対応のため常に空欄"),
            "title_translated": st.column_config.TextColumn("Title", width="large"),
            "published_at": st.column_config.TextColumn("Published"),
            "link": st.column_config.LinkColumn("Link", display_text="Open"),
        },
    )

"""
core/acquisition.py - rss_feeds.csv を読み、直近N日分を取得・翻訳してCSV保存する。
"""

import csv
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from .config import (
    FEEDS_CSV, ITEMS_CSV, DATA_DIR, ensure_dirs,
    FETCH_DELAY_SEC, FETCH_DELAY_DEFAULT_SEC, REDDIT_MAX_PER_SUBREDDIT,
)
from .fetch_feed import fetch_feed_items
from .translator import translate_titles

_COLUMNS = ["platform", "source", "title_translated", "title_original", "comments", "published_at", "link", "fetched_at"]

# Redditは複数サブレを1本の結合URL（hotソート）にまとめて1リクエストで取得するため、
# rss_feeds.csv側は従来どおり1サブレ1行（label・categoryを保持）のまま、urlだけを
# 全行で共有させている。この関数は結果の1件が実際にどのサブレ由来かをlinkから逆引きし、
# 対応する行のlabelに正しく紐付け直す（DESIGN_HISTORY.md「M5」参照）。
_REDDIT_SUB_RE = re.compile(r"reddit\.com/r/([^/]+)/comments/", re.IGNORECASE)


def _resolve_reddit_label(link: str, group: list[dict]) -> str:
    m = _REDDIT_SUB_RE.search(link)
    if not m:
        return group[0]["label"]
    sub = m.group(1).lower()
    for t in group:
        if t["label"].removeprefix("r/").lower() == sub:
            return t["label"]
    return f"r/{m.group(1)}"  # rss_feeds.csv未収載のサブレが結合フィードに混ざっていた場合のフォールバック


def load_feed_targets() -> list[dict]:
    with open(FEEDS_CSV, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _group_targets_by_url(targets: list[dict]) -> list[list[dict]]:
    """同一urlを共有する行（Redditの結合フィード）を1グループにまとめる。urlの初出順を保持する。"""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for t in targets:
        if t["url"] not in groups:
            groups[t["url"]] = []
            order.append(t["url"])
        groups[t["url"]].append(t)
    return [groups[url] for url in order]


def run_acquisition(
    days_back: int,
    translate: bool = True,
    reddit_max_per_subreddit: int = REDDIT_MAX_PER_SUBREDDIT,
) -> pd.DataFrame:
    """フィード一覧の全件を取得し、直近days_back日分をCSV保存し、DataFrameを返す。

    translate=Falseの場合、DeepL呼び出しをスキップしtitle_translatedにtitle_originalをそのまま入れる
    （DEEPL_TOKEN未設定でも動作する。英語圏ユーザーなど翻訳が不要な場合向け。DESIGN_HISTORY.md「M6」参照）。
    reddit_max_per_subredditはReddit結合フィード（§2.1）でサブレ単位にかける件数上限。
    """
    targets = load_feed_targets()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    all_items = []
    groups = _group_targets_by_url(targets)
    for i, group in enumerate(groups):
        platform = group[0]["platform"]
        if i > 0:
            time.sleep(FETCH_DELAY_SEC.get(platform, FETCH_DELAY_DEFAULT_SEC))
        # labelはグループ内の暫定値（1件目）を渡す。複数行が同一urlを共有する場合は
        # 取得後にlinkから逆引きして正しいlabelへ差し替える（下記）。
        items = fetch_feed_items(platform, group[0]["label"], group[0]["url"])
        if len(group) > 1:
            for item in items:
                item.label = _resolve_reddit_label(item.link, group)
        all_items.extend(item for item in items if item.published_at >= cutoff)

    # Reddit結合フィードはhot順（＝活発度順）で返るため、サブレ単位で上限をかけないと
    # 投稿頻度の高いサブレだけで翻訳枠が埋まってしまう。日付フィルタの後、翻訳の前に絞る
    # （翻訳コストを抑える目的。ここで間引かれた分はDeepLに送らない）。
    per_sub_count = defaultdict(int)
    capped_items = []
    for item in all_items:
        if item.platform == "reddit":
            if per_sub_count[item.label] >= reddit_max_per_subreddit:
                continue
            per_sub_count[item.label] += 1
        capped_items.append(item)
    all_items = capped_items

    if translate:
        titles_translated = translate_titles([item.title for item in all_items])
    else:
        titles_translated = [item.title for item in all_items]

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "platform": item.platform,
            "source": item.label,
            "title_translated": title_translated,
            "title_original": item.title,
            "comments": item.comments,
            "published_at": item.published_at.isoformat(),
            "link": item.link,
            "fetched_at": fetched_at,
        }
        for item, title_translated in zip(all_items, titles_translated)
    ]

    df = pd.DataFrame(rows, columns=_COLUMNS)
    df = df.sort_values("published_at", ascending=False).reset_index(drop=True)

    ensure_dirs(DATA_DIR)
    df.to_csv(ITEMS_CSV, index=False, encoding="utf-8")
    return df


def load_saved_items() -> Optional[pd.DataFrame]:
    if not ITEMS_CSV.exists():
        return None
    return pd.read_csv(ITEMS_CSV, encoding="utf-8")

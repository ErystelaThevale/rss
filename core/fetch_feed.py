"""
core/fetch_feed.py - RSS/Atom フィードの汎用取得（HN/Reddit/Lemmy共通）
"""

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import feedparser

from .config import warn, RETRY_ON_429_WAIT_SEC, RETRY_ON_429_MAX_ATTEMPTS

# Reddit等が汎用UAでの取得を弾く事例があるため、ブラウザ相当のUAを付与する。
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_TIMEOUT = 20

# コメント数はプラットフォームごとにdescription内の定型文言から正規表現で抽出する
# （Reddit未認証.rssにはコメント数フィールド自体が存在しないため対象外。DESIGN_NOTES.md §2参照）。
# hnrss.orgのdescriptionは "<p># Comments: 6</p>" という固定文言を持つ。
_HN_COMMENTS_RE = re.compile(r"#\s*Comments:\s*(\d+)")
# LemmyのdescriptionはCDATA内に投稿本文も含むため、本文中の数字を誤検出しないよう
# "N points | <a href=...>N comments</a>" の "|" 直後のアンカー要素に絞って抽出する。
_LEMMY_COMMENTS_RE = re.compile(r"\|\s*<a[^>]*>\s*(\d+)\s*comments?\s*</a>", re.IGNORECASE)


@dataclass
class FeedItem:
    platform: str
    label: str
    title: str
    link: str
    published_at: datetime  # tz-aware UTC
    comments: Optional[int] = None  # 現在のコメント数（活性度の指標）。取得不能な場合はNone


def fetch_feed_items(platform: str, label: str, url: str) -> list[FeedItem]:
    """1フィードを取得し、日付付きアイテムのリストを返す（日付フィルタはしない）。取得失敗時は空リスト。

    429（レート制限）は最大RETRY_ON_429_MAX_ATTEMPTS回まで、RETRY_ON_429_WAIT_SEC秒間隔でリトライする
    （実測: Redditの成功は45〜60秒に1回のtime window依存のため、1回の再試行だけでは復帰しないことが多い。
    DESIGN_HISTORY.md「M5」参照）。
    """
    parsed = None
    for attempt in range(RETRY_ON_429_MAX_ATTEMPTS):
        if attempt > 0:
            warn(f"{label}: HTTP 429（レート制限）。{RETRY_ON_429_WAIT_SEC}秒待って再試行（{attempt + 1}/{RETRY_ON_429_MAX_ATTEMPTS}）")
            time.sleep(RETRY_ON_429_WAIT_SEC)
        try:
            parsed = feedparser.parse(url, agent=_USER_AGENT, request_headers={"User-Agent": _USER_AGENT})
        except Exception as e:
            warn(f"{label}: 取得例外 {e}")
            return []
        if parsed.get("status") != 429:
            break

    status = parsed.get("status")
    if status is not None and status >= 400:
        warn(f"{label}: HTTP {status}（0件扱い）")
        return []
    if not parsed.entries and parsed.get("bozo"):
        warn(f"{label}: パース失敗 {parsed.get('bozo_exception')}")
        return []

    items = []
    for entry in parsed.entries:
        published_at = _extract_published(entry)
        title = (entry.get("title") or "").strip()
        link = _extract_link(platform, entry)
        if not title or not link or published_at is None:
            continue
        comments = _extract_comment_count(platform, entry)
        items.append(FeedItem(platform=platform, label=label, title=title, link=link, published_at=published_at, comments=comments))
    return items


def _extract_published(entry) -> Optional[datetime]:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    return None


def _extract_link(platform: str, entry) -> str:
    """HNへコメントを返せるよう、HNのみHNスレッドURL（entry.comments）をlinkとして採用する。

    hnrss.orgのentry.linkは記事本体ではなく記事に埋め込まれた外部URL（Article URL）を指すため、
    entry.link をそのまま使うとHN本体のスレッドに辿り着けない（2026-08-14、ユーザー指摘・実地確認）。
    entry.comments はhnrssが常に付与するHN本体のitemページURL。念のため欠落時はentry.linkへフォールバックする。
    Lemmy/Redditはentry.link自体が投稿＝コメント欄ページを指すため変更不要（実地確認済み）。
    """
    if platform == "hn":
        return (entry.get("comments") or entry.get("link") or "").strip()
    return (entry.get("link") or "").strip()


def _extract_comment_count(platform: str, entry) -> Optional[int]:
    """現在のコメント数を description からプラットフォーム別の定型パターンで抽出する。"""
    if platform == "hn":
        pattern = _HN_COMMENTS_RE
    elif platform == "lemmy":
        pattern = _LEMMY_COMMENTS_RE
    else:
        return None  # reddit: 未認証.rssにコメント数フィールドが存在しないため対象外
    m = pattern.search(entry.get("summary") or "")
    return int(m.group(1)) if m else None

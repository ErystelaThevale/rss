"""
core/config.py - パス定数・環境変数・共通ユーティリティ
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# core → rss (ツール自身のフォルダ基準。Strategy側のディレクトリ構造には依存しない
# ことで、rss/ フォルダごと他リポジトリへコピーしてもそのまま動く)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FEEDS_CSV = DATA_DIR / "rss_feeds.csv"
ITEMS_CSV = DATA_DIR / "rss_items.csv"

DEEPL_TOKEN = os.getenv("DEEPL_TOKEN")

# 翻訳先言語（DeepLの target_lang コード）。source_langは指定せずDeepLの自動判定に任せる
# （フィードごと・記事ごとに元言語が混在しても機能する）。
TARGET_LANG = os.getenv("RSS_TARGET_LANG", "JA")

DEFAULT_DAYS_BACK = 7

# Redditはunauthenticatedな .rss 取得がIP単位・時間窓ベースでレート制限される
# （2026-08-14実測: サブレ個別に叩くと成功は45〜60秒に1回のみで、どのサブレを叩いているかは無関係。
# 429応答は0.2秒でエッジ側から即返り、200は0.6〜1秒かかる＝実サーバーまで到達している。
# DESIGN_HISTORY.md「M5」参照）。プラットフォーム別に取得間隔を分ける。
FETCH_DELAY_SEC = {
    "reddit": 15,
}
FETCH_DELAY_DEFAULT_SEC = 0
RETRY_ON_429_WAIT_SEC = 50  # 実測の時間窓（45〜60秒）に合わせる。20秒では窓に届かず再試行も429になるケースを確認済み
RETRY_ON_429_MAX_ATTEMPTS = 3  # 初回+2リトライ。Reddit結合フィードは1回のfetchに集約したため、多少待ってでも確実に取得する方を優先

# Reddit結合フィード（1URLに複数サブレをまとめて1リクエストで取得）から、翻訳に回す前に
# サブレ単位で件数上限をかける（hot順で活発なサブレが枠を独占し、翻訳コストも偏るのを防ぐ）。
# DESIGN_HISTORY.md「M5」参照。
REDDIT_MAX_PER_SUBREDDIT = 5


def ensure_dirs(*paths: Path):
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def log(msg: str):
    print(msg)


def warn(msg: str):
    print(f"[warn] {msg}")

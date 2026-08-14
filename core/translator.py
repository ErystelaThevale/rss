"""
core/translator.py - DeepL APIによるタイトル一括翻訳
"""

import requests

from .config import DEEPL_TOKEN, TARGET_LANG

_MAX_TEXTS_PER_REQUEST = 50  # DeepL /v2/translate の1リクエストあたりtext上限
_TIMEOUT = 60


def translate_titles(titles: list[str], target_lang: str = TARGET_LANG) -> list[str]:
    """タイトルのリストをDeepL APIでまとめてtarget_langに翻訳する。順序は入力と対応。

    source_langは指定しない（DeepL側の自動言語判定に任せる）。フィードごと・
    記事ごとに元言語が混在していても機能する。ただしRSSタイトルのような短文は
    自動判定の精度がやや落ちる場合がある（DeepL公式ドキュメント記載の既知の制約）。
    """
    if not titles:
        return []
    if not DEEPL_TOKEN:
        raise RuntimeError("DEEPL_TOKEN is not set in .env")

    base = "api-free.deepl.com" if DEEPL_TOKEN.endswith(":fx") else "api.deepl.com"
    url = f"https://{base}/v2/translate"

    results: list[str] = []
    for i in range(0, len(titles), _MAX_TEXTS_PER_REQUEST):
        chunk = titles[i:i + _MAX_TEXTS_PER_REQUEST]
        resp = requests.post(
            url,
            headers={"Authorization": f"DeepL-Auth-Key {DEEPL_TOKEN}"},
            json={"text": chunk, "target_lang": target_lang},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results.extend(t["text"] for t in resp.json()["translations"])
    return results

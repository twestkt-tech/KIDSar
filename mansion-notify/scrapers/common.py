# -*- coding: utf-8 -*-
"""スクレイパー共通ユーティリティ"""

import re
import sys
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.8",
}

FETCH_INTERVAL_SEC = 2  # サーバー負荷への配慮


def fetch(url: str) -> str | None:
    try:
        res = requests.get(url, headers=HEADERS, timeout=30)
        res.raise_for_status()
        time.sleep(FETCH_INTERVAL_SEC)
        return res.text
    except requests.RequestException as e:
        print(f"[WARN] 取得失敗: {url} ({e})", file=sys.stderr)
        return None


def parse_price(text: str) -> float | None:
    """'2,980万円' '1億2000万円' → 万円単位の数値"""
    text = (text or "").replace(",", "").replace(" ", "")
    m = re.search(r"(?:(\d+)億)?(\d+(?:\.\d+)?)?万円", text)
    if not m:
        return None
    oku = int(m.group(1)) * 10000 if m.group(1) else 0
    man = float(m.group(2)) if m.group(2) else 0
    return oku + man


def parse_area(text: str) -> float | None:
    """'70.2m2' '70.2㎡' → 数値"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m2|m²|㎡)", text or "")
    return float(m.group(1)) if m else None

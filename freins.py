# -*- coding: utf-8 -*-
"""
ふれんず(f-takken.com)専用スクレイパー

ふれんずは検索結果をJavaScriptで /items エンドポイントから読み込む方式。
_token はセッションごとに変わるため、毎回検索ページから自動取得して付け直す。

config.yaml の書き方:
  - name: ふれんず 福岡市 中古マンション
    type: freins
    enabled: true
    url: "(ブラウザで検索したときの items?...&_token=... のURLをそのまま貼る。トークンは自動更新)"
"""

import json
import re
import sys
import time
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .common import HEADERS, parse_price, parse_area

BASE = "https://www.f-takken.com"


def _get_token(session: requests.Session, entry_url: str) -> str | None:
    """検索ページを開いてCSRFトークンを取得"""
    try:
        r = session.get(entry_url, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[WARN] ふれんず: トークン取得ページの読込失敗 ({e})", file=sys.stderr)
        return None
    for pattern in (
        r'name="_token"\s+value="([^"]+)"',
        r'"_token"\s*:\s*"([^"]+)"',
        r'_token=([A-Za-z0-9]{20,})',
        r'name="csrf-token"\s+content="([^"]+)"',
    ):
        m = re.search(pattern, r.text)
        if m:
            return m.group(1)
    print("[WARN] ふれんず: ページ内にトークンが見つかりませんでした", file=sys.stderr)
    return None


def _parse_items_html(html: str, debug: bool = False) -> list[dict]:
    """itemsエンドポイントが返すHTML断片から物件を抽出"""
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # 物件詳細へのリンク(数字IDで終わるURL)を核に、その周辺ブロックを1物件とみなす
    seen_links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"/freins/(?:view|detail|bukken)[^\"]*\d|/freins/[a-z/]+/\d{5,}", href):
            continue
        link = urljoin(BASE, href.split("?")[0])
        if link in seen_links:
            continue
        seen_links.add(link)

        # リンクを含む「物件カード」らしき祖先要素を探す
        block = a
        for _ in range(6):
            if block.parent is None:
                break
            block = block.parent
            cls = " ".join(block.get("class", []))
            if any(k in cls for k in ("item", "bukken", "property", "result", "card", "estate")):
                break

        text = block.get_text(" ", strip=True)
        price = parse_price(text)
        area = parse_area(text)
        layout_m = re.search(r"([1-9１-９](?:LDK|DK|K|R|ＬＤＫ|ＤＫ|Ｋ)[\+＋]?[SＳ]?)", text)
        addr_m = re.search(r"(福岡[市県][^\s/｜|]{2,20})", text)
        built_m = re.search(r"((?:19|20)\d{2}年\d{1,2}月|築\d+年)", text)

        name = a.get_text(strip=True)
        if not name or len(name) < 3:
            img = block.find("img", alt=True)
            name = img["alt"] if img else text[:30]

        listings.append({
            "id": link,
            "name": name[:60],
            "url": link,
            "price_text": f"{price:.0f}万円".replace(".0", "") if price else "",
            "price_man": price,
            "address": addr_m.group(1) if addr_m else "",
            "station": "",
            "area_text": f"{area}㎡" if area else "",
            "area_m2": area,
            "layout": layout_m.group(1) if layout_m else "",
            "built": built_m.group(1) if built_m else "",
        })

    if not listings and debug:
        print("[DEBUG] ふれんず: 物件リンクを検出できませんでした。応答の先頭を表示します:")
        print(html[:2000])
    return listings


def _parse_items_json(data) -> list[dict]:
    """itemsエンドポイントがJSONを返す場合の抽出(構造は柔軟に探索)"""
    # リストを含みそうなキーを探す
    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("items", "data", "list", "bukken", "results", "properties"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        # HTMLがJSONに包まれているパターン
        for key in ("html", "view", "body"):
            if isinstance(data.get(key), str) and "<" in data[key]:
                return _parse_items_html(data[key])
    if not items:
        return []

    listings = []
    for it in items:
        if not isinstance(it, dict):
            continue
        link = it.get("url") or it.get("link") or ""
        if link and not link.startswith("http"):
            link = urljoin(BASE, link)
        if not link:
            continue
        price_text = str(it.get("price", it.get("kakaku", "")))
        area_text = str(it.get("area", it.get("menseki", "")))
        listings.append({
            "id": link,
            "name": str(it.get("name", it.get("title", it.get("bukken_name", link))))[:60],
            "url": link,
            "price_text": price_text,
            "price_man": parse_price(price_text),
            "address": str(it.get("address", it.get("jusho", ""))),
            "station": str(it.get("station", "")),
            "area_text": area_text,
            "area_m2": parse_area(area_text),
            "layout": str(it.get("layout", it.get("madori", ""))),
            "built": str(it.get("built", it.get("chikunen", ""))),
        })
    return listings


def scrape(source: dict) -> list[dict]:
    url = source["url"]
    split = urlsplit(url)
    items_url = f"{split.scheme}://{split.netloc}{split.path}"
    # /items を除いたページが検索画面(トークン取得元)
    entry_url = items_url.rsplit("/items", 1)[0]

    # クエリから古い_tokenを除去(locate[]の重複を保持するためタプルのリストで扱う)
    params = [(k, v) for k, v in parse_qsl(split.query, keep_blank_values=True)
              if k != "_token"]

    session = requests.Session()
    session.headers.update(HEADERS)

    token = _get_token(session, entry_url)
    if token:
        params.append(("_token", token))
    time.sleep(2)

    try:
        res = session.get(
            items_url,
            params=params,
            headers={"X-Requested-With": "XMLHttpRequest", "Referer": entry_url},
            timeout=30,
        )
        res.raise_for_status()
    except requests.RequestException as e:
        print(f"[WARN] ふれんず: 物件データ取得失敗 ({e})", file=sys.stderr)
        return []

    body = res.text.strip()
    listings = []
    if body.startswith("{") or body.startswith("["):
        try:
            listings = _parse_items_json(json.loads(body))
        except json.JSONDecodeError:
            pass
    if not listings:
        listings = _parse_items_html(body, debug=True)

    for it in listings:
        it["source"] = source["name"]
    return listings

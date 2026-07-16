# -*- coding: utf-8 -*-
"""
汎用スクレイパー
config.yaml の selectors 定義だけで任意のサイトに対応する。
コードを書かずに、ブラウザの開発者ツールで調べたCSSセレクタを
設定に書けばよい。

設定例:
  - name: ノムコム 福岡 中古マンション
    type: generic
    url: "https://www.nomu.com/mansion/area_fukuoka/..."
    enabled: true
    max_pages: 2
    pagination:
      param: page            # ?page=2 形式。 "path:{n}" 形式も可
    selectors:
      item: ".p-searchList__item"     # 物件1件を囲む要素(必須)
      title: ".p-searchList__title"   # 物件名(必須)
      link: "a"                       # リンク(hrefを取得、必須)
      price: ".price"                 # 価格テキスト
      address: ".address"             # 所在地
      layout: ".layout"               # 間取り
      area: ".area"                   # 面積
      station: ".station"             # 最寄駅
      built: ".built"                 # 築年月
"""

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import fetch, parse_price, parse_area


def _text(el, selector: str | None) -> str:
    if not selector:
        return ""
    found = el.select_one(selector)
    return found.get_text(" ", strip=True) if found else ""


def _page_url(base_url: str, pagination: dict | None, page: int) -> str | None:
    if page == 1:
        return base_url
    if not pagination:
        return None  # ページネーション未定義なら1ページのみ
    param = pagination.get("param")
    if param:
        sep = "&" if "?" in base_url else "?"
        return f"{base_url}{sep}{param}={page}"
    path = pagination.get("path")  # 例: "https://.../list/{n}/"
    if path:
        return path.replace("{n}", str(page))
    return None


def scrape(source: dict) -> list[dict]:
    sel = source.get("selectors", {})
    if not sel.get("item") or not sel.get("title") or not sel.get("link"):
        print(f"[WARN] {source['name']}: selectors(item/title/link)が未設定のためスキップ")
        return []

    listings = []
    max_pages = source.get("max_pages", 1)

    for page in range(1, max_pages + 1):
        page_url = _page_url(source["url"], source.get("pagination"), page)
        if page_url is None:
            break
        html = fetch(page_url)
        if html is None:
            break

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(sel["item"])
        if not items:
            if page == 1:
                print(f"[WARN] {source['name']}: 物件要素が見つかりません。"
                      f"セレクタ '{sel['item']}' を確認してください。")
            break

        for item in items:
            link_el = item.select_one(sel["link"])
            href = link_el.get("href", "") if link_el else ""
            if not href:
                continue
            link = urljoin(source["url"], href)

            price_text = _text(item, sel.get("price"))
            area_text = _text(item, sel.get("area"))

            listings.append({
                "id": link,
                "name": _text(item, sel["title"]) or link,
                "url": link,
                "price_text": price_text,
                "price_man": parse_price(price_text),
                "address": _text(item, sel.get("address")),
                "station": _text(item, sel.get("station")),
                "area_text": area_text,
                "area_m2": parse_area(area_text),
                "layout": _text(item, sel.get("layout")),
                "built": _text(item, sel.get("built")),
                "source": source["name"],
            })
    return listings

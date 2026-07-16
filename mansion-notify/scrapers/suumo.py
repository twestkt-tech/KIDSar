# -*- coding: utf-8 -*-
"""SUUMO 中古マンション/戸建・土地 検索結果スクレイパー"""

from bs4 import BeautifulSoup

from .common import fetch, parse_price, parse_area


def scrape(source: dict) -> list[dict]:
    url = source["url"]
    max_pages = source.get("max_pages", 3)
    listings = []

    for page in range(1, max_pages + 1):
        page_url = url if page == 1 else f"{url}{'&' if '?' in url else '?'}pn={page}"
        html = fetch(page_url)
        if html is None:
            break

        soup = BeautifulSoup(html, "html.parser")
        units = soup.select(".property_unit")
        if not units:
            break

        for unit in units:
            title_el = unit.select_one(".property_unit-title a")
            if not title_el:
                continue
            href = title_el.get("href", "")
            link = "https://suumo.jp" + href if href.startswith("/") else href

            detail = {}
            for dl in unit.select(".dottable-line dl"):
                dt, dd = dl.select_one("dt"), dl.select_one("dd")
                if dt and dd:
                    detail[dt.get_text(strip=True)] = dd.get_text(strip=True)

            price_text = detail.get("販売価格", "")
            area_text = detail.get("専有面積", detail.get("建物面積", detail.get("土地面積", "")))

            listings.append({
                "id": link,
                "name": title_el.get_text(strip=True),
                "url": link,
                "price_text": price_text,
                "price_man": parse_price(price_text),
                "address": detail.get("所在地", ""),
                "station": detail.get("沿線・駅", ""),
                "area_text": area_text,
                "area_m2": parse_area(area_text),
                "layout": detail.get("間取り", ""),
                "built": detail.get("築年月", ""),
                "source": source["name"],
            })
    return listings

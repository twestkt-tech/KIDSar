# -*- coding: utf-8 -*-
"""スクレイパー登録簿。sourceの type に応じて振り分ける。"""

from . import suumo, generic

SCRAPERS = {
    "suumo": suumo.scrape,
    "generic": generic.scrape,
}


def scrape(source: dict) -> list[dict]:
    stype = source.get("type", "generic")
    if stype not in SCRAPERS:
        raise ValueError(f"未対応のtype: {stype}")
    return SCRAPERS[stype](source)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
不動産新着通知システム(マルチサイト対応)
config.yaml に定義した各サイトの検索結果を巡回し、
新着物件をLINE(Messaging API)に通知する。

使い方:
  python main.py                     # 通常実行(新着チェック→LINE通知)
  python main.py --test "ソース名"   # 1ソースだけ取得して結果を画面表示(通知なし)
  python main.py --dry-run           # 全ソース取得・新着判定するがLINEには送らない
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
import yaml

import scrapers

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
SEEN_PATH = BASE_DIR / "seen.json"


# ---------------------------------------------------------------- 設定・状態
def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen() -> set:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text(encoding="utf-8")))
    return set()


def save_seen(seen: set) -> None:
    SEEN_PATH.write_text(
        json.dumps(sorted(seen)[-20000:], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- フィルタ
def match_filters(item: dict, f: dict) -> bool:
    if f.get("price_max_man") and item["price_man"] and item["price_man"] > f["price_max_man"]:
        return False
    if f.get("price_min_man") and item["price_man"] and item["price_man"] < f["price_min_man"]:
        return False
    if f.get("area_min_m2") and item["area_m2"] and item["area_m2"] < f["area_min_m2"]:
        return False
    layouts = f.get("layouts")
    if layouts and item["layout"] and not any(l in item["layout"] for l in layouts):
        return False
    blob = f'{item["name"]} {item["address"]}'
    if any(k in blob for k in (f.get("exclude_keywords") or [])):
        return False
    include = f.get("include_keywords") or []
    if include and not any(k in blob for k in include):
        return False
    return True


# ---------------------------------------------------------------- LINE通知
def send_line(messages: list[str], token: str, user_id: str) -> None:
    endpoint = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    for i in range(0, len(messages), 5):
        payload = {
            "to": user_id,
            "messages": [{"type": "text", "text": m[:4900]} for m in messages[i:i + 5]],
        }
        res = requests.post(endpoint, headers=headers, json=payload, timeout=30)
        if res.status_code != 200:
            print(f"[ERROR] LINE送信失敗: {res.status_code} {res.text}", file=sys.stderr)


def format_listing(item: dict) -> str:
    lines = [f"🏢 {item['name']}"]
    spec = "  ".join(x for x in [item["price_text"], item["layout"], item["area_text"]] if x)
    if spec:
        lines.append(f"💰 {spec}")
    if item["address"]:
        lines.append(f"📍 {item['address']}")
    if item["station"]:
        lines.append(f"🚉 {item['station']}")
    if item["built"]:
        lines.append(f"🗓 {item['built']}")
    lines.append(f"[{item['source']}]")
    lines.append(item["url"])
    return "\n".join(lines)


# ---------------------------------------------------------------- メイン
def run_test(config: dict, source_name: str) -> None:
    for source in config.get("sources", []):
        if source["name"] == source_name:
            items = scrapers.scrape(source)
            print(f"=== {source_name}: {len(items)} 件取得 ===")
            for it in items[:5]:
                print("-" * 40)
                print(format_listing(it))
            if not items:
                print("0件でした。URLとselectorsを確認してください。")
            return
    print(f"[ERROR] ソース '{source_name}' がconfig.yamlに見つかりません")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", metavar="ソース名", help="1ソースのみ取得して表示(通知・既読更新なし)")
    ap.add_argument("--dry-run", action="store_true", help="LINE送信せず新着判定のみ")
    args = ap.parse_args()

    config = load_config()

    if args.test:
        run_test(config, args.test)
        return

    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not args.dry_run and (not token or not user_id):
        print("[ERROR] 環境変数 LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID を設定してください", file=sys.stderr)
        sys.exit(1)

    seen = load_seen()
    first_run = len(seen) == 0
    new_items = []

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        print(f"[INFO] 巡回中: {source['name']}")
        try:
            items = scrapers.scrape(source)
        except Exception as e:
            print(f"[WARN] {source['name']} でエラー: {e}", file=sys.stderr)
            continue
        print(f"[INFO]  取得 {len(items)} 件")
        for item in items:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            if match_filters(item, config.get("filters", {})):
                new_items.append(item)

    save_seen(seen)

    if first_run:
        print(f"[INFO] 初回実行: {len(seen)} 件を既読登録。次回から新着のみ通知します。")
        if not args.dry_run:
            send_line(
                [f"✅ 新着物件通知システムを開始しました。\n現在の掲載 {len(seen)} 件を登録済み。今後は新着のみお知らせします。"],
                token, user_id,
            )
        return

    if not new_items:
        print("[INFO] 新着なし")
        return

    print(f"[INFO] 新着 {len(new_items)} 件")
    if args.dry_run:
        for it in new_items:
            print("-" * 40)
            print(format_listing(it))
        return

    header = f"🆕 条件に合う新着物件 {len(new_items)} 件"
    body = "\n\n────────\n\n".join(format_listing(i) for i in new_items[:10])
    if len(new_items) > 10:
        body += f"\n\n…ほか {len(new_items) - 10} 件"
    send_line([header + "\n\n" + body], token, user_id)


if __name__ == "__main__":
    main()

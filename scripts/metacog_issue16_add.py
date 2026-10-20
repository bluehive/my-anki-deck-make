#!/usr/bin/env python3
"""02メタ認知アップへ「学ぶ順番」のカードを追加する（Issue #16）。

既定は dry-run。--apply を付けたときだけ AnkiConnect に書き込む。
デッキ内に同じ表面が無いカードだけ addNote する。
updateNoteFields と deleteNotes は呼ばない。再実行しても追加は 0 件。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "metacog_deck.csv"
ANKI_CONNECT_URL = "http://localhost:8765"
DECK_NAME = "02メタ認知アップ"
CATEGORY = "学ぶ順番"
PROJECT_TAG = "anki-mydeck-make"
WRITE_ACTIONS = frozenset({"updateNoteFields", "addNote", "deleteNotes"})


class InvokeResult:
    """AnkiConnect の応答。成功時の result が null でも ok と区別する。"""

    def __init__(self, ok: bool, value):
        self.ok = ok
        self.value = value


def invoke(action: str, params: dict | None = None) -> InvokeResult:
    """AnkiConnect にリクエストを送る。書き込みは呼び出し側が --apply のときだけ行う。"""
    payload = {"action": action, "version": 6, "params": params or {}}
    try:
        response = requests.post(ANKI_CONNECT_URL, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        print(f"[接続エラー] Ankiが起動しているか、AnkiConnectアドオンが有効か確認してください: {exc}")
        return InvokeResult(False, None)
    if result.get("error"):
        print(f"[AnkiConnect Error] {action}: {result['error']}")
        return InvokeResult(False, None)
    return InvokeResult(True, result.get("result"))


def note_tags(category: str) -> list[str]:
    tags = ["metacog", PROJECT_TAG]
    if category:
        tags.append(category)
    return tags


def front_of(note: dict) -> str:
    fields = note.get("fields") or {}
    front = fields.get("Front") or {}
    if isinstance(front, dict):
        return front.get("value") or ""
    return str(front)


def _ok_value(result):
    """InvokeResult でも、テスト用の素の戻り値でも読めるようにする。"""
    if isinstance(result, InvokeResult):
        if not result.ok:
            return None
        return result.value
    return result


def load_new_cards(path: Path = CSV_PATH) -> list[dict]:
    """生成済み CSV から「学ぶ順番」のカードだけを、並びを保って読む。"""
    if not path.is_file():
        raise SystemExit(f"CSV が見つかりません: {path}")
    cards = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("カテゴリ") != CATEGORY:
                continue
            front = row.get("表面") or ""
            back = row.get("裏面") or ""
            if not front.strip() or not back.strip():
                raise SystemExit(f"空欄のカードがあります: {front!r}")
            cards.append({"front": front, "back": back, "category": CATEGORY})
    if not cards:
        raise SystemExit(f"{CATEGORY} のカードが CSV にありません: {path}")
    return cards


def find_notes_by_front(deck: str, front: str, invoke_fn=invoke) -> list[dict] | None:
    """デッキ内で表面が完全一致するノートを返す。接続失敗は None。"""
    query = f'deck:"{deck}" "Front:{front}"'
    found = _ok_value(invoke_fn("findNotes", {"query": query}))
    if found is None:
        return None
    if not found:
        return []
    infos = _ok_value(invoke_fn("notesInfo", {"notes": found}))
    if infos is None:
        return None
    matched = []
    for note in infos:
        if front_of(note) == front:
            matched.append({"noteId": note["noteId"]})
    return matched


def plan_addition(cards: list[dict], invoke_fn=invoke, deck: str = DECK_NAME) -> dict:
    """書き込まずに、追加とスキップの予定を組み立てる。更新・削除は予定しない。"""
    adds = []
    skips = []
    for card in cards:
        existing = find_notes_by_front(deck, card["front"], invoke_fn)
        if existing is None:
            skips.append(
                {
                    "front": card["front"],
                    "reason": "AnkiConnect への問い合わせに失敗した",
                }
            )
            continue
        if existing:
            skips.append(
                {
                    "front": card["front"],
                    "reason": "表面が既にデッキ内にあるので追加しない",
                    "count": len(existing),
                }
            )
            continue
        adds.append(card)
    return {"deck": deck, "adds": adds, "skips": skips, "updates": [], "deletes": []}


def apply_plan(plan: dict, invoke_fn=invoke) -> dict:
    """addNote だけを送る。updateNoteFields と deleteNotes は送らない。"""
    added = 0
    for item in plan["adds"]:
        result = invoke_fn(
            "addNote",
            {
                "note": {
                    "deckName": plan["deck"],
                    "modelName": "Basic",
                    "fields": {"Front": item["front"], "Back": item["back"]},
                    "tags": note_tags(item["category"]),
                }
            },
        )
        if _ok_value(result) is not None:
            added += 1
    return {"added": added, "updated": 0, "deleted": 0}


def print_plan(plan: dict) -> None:
    print(f"デッキ: {plan['deck']}")
    print(f"追加予定: {len(plan['adds'])}件 / スキップ: {len(plan['skips'])}件")
    for item in plan["adds"]:
        print(f"[追加予定] {item['front']}")
    for item in plan["skips"]:
        print(f"[スキップ] {item['front']} — {item['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="メタ認知デッキへ学ぶ順番のカードを追加する（既定は dry-run）"
    )
    parser.add_argument("--apply", action="store_true", help="AnkiConnect に書き込む。省略時は dry-run")
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    args = parser.parse_args(argv)

    cards = load_new_cards(args.csv)
    plan = plan_addition(cards)
    print_plan(plan)
    if not args.apply:
        print("dry-run のため書き込みません。反映するには --apply を付けて再実行してください。")
        return 0

    result = apply_plan(plan)
    print(
        f"適用しました: add {result['added']}件 / update {result['updated']}件 / delete {result['deleted']}件"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

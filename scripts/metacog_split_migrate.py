#!/usr/bin/env python3
"""02メタ認知アップの複合カード5枚を、履歴を残したまま分割する。

既定は dry-run。--apply を付けたときだけ AnkiConnect に書き込む。
先頭カード（★）は noteId を指定して updateNoteFields する。
残りは addNote。表面が既にあれば追加しない。deleteNotes は使わない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
MAPPING_PATH = ROOT / "data" / "metacog_split" / "mapping.json"
ANKI_CONNECT_URL = "http://localhost:8765"
PROJECT_TAG = "anki-mydeck-make"
WRITE_ACTIONS = frozenset({"updateNoteFields", "addNote", "deleteNotes"})


def load_mapping(path: Path = MAPPING_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("deck") or not data.get("splits"):
        raise SystemExit(f"対応表が不正です: {path}")
    for split in data["splits"]:
        cards = split.get("cards") or []
        if len(cards) < 2:
            raise SystemExit(f"分割 {split.get('id')} の新カードが2枚未満です")
        if not split.get("old_front"):
            raise SystemExit(f"分割 {split.get('id')} に元の表面がありません")
    return data


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


def find_note_ids_by_front(deck: str, front: str, invoke_fn=invoke) -> list[int] | None:
    """デッキ内で表面が完全一致する noteId を返す。接続失敗は None。"""
    query = f'deck:"{deck}" "Front:{front}"'
    found = _ok_value(invoke_fn("findNotes", {"query": query}))
    if found is None:
        return None
    if not found:
        return []
    infos = _ok_value(invoke_fn("notesInfo", {"notes": found}))
    if infos is None:
        return None
    matched = [note["noteId"] for note in infos if front_of(note) == front]
    return matched


def plan_migration(mapping: dict, invoke_fn=invoke) -> dict:
    """書き込まずに、更新・追加・スキップの予定を組み立てる。"""
    deck = mapping["deck"]
    updates = []
    adds = []
    skips = []

    for split in mapping["splits"]:
        old_front = split["old_front"]
        cards = split["cards"]
        star = cards[0]
        extras = cards[1:]
        note_ids = find_note_ids_by_front(deck, old_front, invoke_fn)
        if note_ids is None:
            skips.append(
                {
                    "id": split["id"],
                    "old_front": old_front,
                    "reason": "AnkiConnect への問い合わせに失敗した",
                }
            )
            continue
        if len(note_ids) != 1:
            reason = "0件" if len(note_ids) == 0 else f"{len(note_ids)}件"
            skips.append(
                {
                    "id": split["id"],
                    "old_front": old_front,
                    "reason": f"元の表面に完全一致するノートが{reason}（ちょうど1件ではないので書き込まない）",
                    "count": len(note_ids),
                }
            )
            continue

        note_id = note_ids[0]
        updates.append(
            {
                "id": split["id"],
                "note_id": note_id,
                "old_front": old_front,
                "old_back": split.get("old_back", ""),
                "new_front": star["front"],
                "new_back": star["back"],
                "category": star["category"],
            }
        )
        for card in extras:
            existing = find_note_ids_by_front(deck, card["front"], invoke_fn)
            if existing is None:
                skips.append(
                    {
                        "id": split["id"],
                        "old_front": old_front,
                        "front": card["front"],
                        "reason": "追加候補の照合に失敗した",
                    }
                )
                continue
            if existing:
                skips.append(
                    {
                        "id": split["id"],
                        "old_front": old_front,
                        "front": card["front"],
                        "reason": "表面が既にデッキ内にあるので追加しない",
                        "count": len(existing),
                    }
                )
                continue
            adds.append(
                {
                    "id": split["id"],
                    "front": card["front"],
                    "back": card["back"],
                    "category": card["category"],
                }
            )

    return {"deck": deck, "updates": updates, "adds": adds, "skips": skips}


def apply_plan(plan: dict, invoke_fn=invoke) -> dict:
    """updateNoteFields と addNote だけを送る。deleteNotes は送らない。"""
    updated = 0
    added = 0
    for item in plan["updates"]:
        result = invoke_fn(
            "updateNoteFields",
            {
                "note": {
                    "id": item["note_id"],
                    "fields": {
                        "Front": item["new_front"],
                        "Back": item["new_back"],
                    },
                }
            },
        )
        if isinstance(result, InvokeResult):
            if result.ok:
                updated += 1
        elif result is not False:
            updated += 1
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
        value = _ok_value(result)
        if value is not None:
            added += 1
    return {"updated": updated, "added": added, "deleted": 0}


def print_plan(plan: dict) -> None:
    print(f"デッキ: {plan['deck']}")
    print(f"更新予定: {len(plan['updates'])}件 / 追加予定: {len(plan['adds'])}件 / スキップ: {len(plan['skips'])}件")
    for item in plan["updates"]:
        print(
            f"[更新予定] id={item['id']} noteId={item['note_id']}\n"
            f"  旧: {item['old_front']}\n"
            f"  新: {item['new_front']}"
        )
    for item in plan["adds"]:
        print(f"[追加予定] id={item['id']} {item['front']}")
    for item in plan["skips"]:
        front = item.get("front") or item.get("old_front")
        print(f"[スキップ] id={item['id']} {front} — {item['reason']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="メタ認知デッキの複合カードを分割移行する（既定は dry-run）")
    parser.add_argument("--apply", action="store_true", help="AnkiConnect に書き込む。省略時は dry-run")
    parser.add_argument("--mapping", type=Path, default=MAPPING_PATH)
    args = parser.parse_args(argv)

    mapping = load_mapping(args.mapping)
    plan = plan_migration(mapping)
    print_plan(plan)
    if not args.apply:
        print("dry-run のため書き込みません。反映するには --apply を付けて再実行してください。")
        return 0

    result = apply_plan(plan)
    print(
        f"適用しました: update {result['updated']}件 / add {result['added']}件 / delete {result['deleted']}件"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

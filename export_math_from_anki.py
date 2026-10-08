#!/usr/bin/env python3
"""高校数学・基礎解析デッキを AnkiConnect から読み取り専用で書き出す。

Anki 上の現在値が正。Text / Back Extra は生 HTML のまま保存する。
このスクリプトは findNotes と notesInfo だけを呼ぶ。更新・削除はしない。
"""

import csv
import json
from datetime import datetime
from pathlib import Path

import requests

ANKI_CONNECT_URL = "http://localhost:8765"
DECK_NAME = "高校数学・基礎解析"
OUT_DIR = Path("data/math_v2")
CSV_PATH = OUT_DIR / "anki_export.csv"
CSV_FIELDS = ["noteId", "Text", "Back Extra", "Tags"]


def invoke(action, params=None):
    payload = {"action": action, "version": 6, "params": params or {}}
    response = requests.post(ANKI_CONNECT_URL, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()
    if result.get("error"):
        raise RuntimeError(f"{action}: {result['error']}")
    return result.get("result")


def main():
    note_ids = invoke("findNotes", {"query": f'deck:"{DECK_NAME}"'}) or []
    note_ids = sorted(note_ids)
    if len(note_ids) != 100:
        raise SystemExit(f"ノート数が 100 ではありません: {len(note_ids)}")

    notes = invoke("notesInfo", {"notes": note_ids}) or []
    notes = sorted(notes, key=lambda note: note["noteId"])
    if [note["noteId"] for note in notes] != note_ids:
        raise SystemExit("notesInfo の noteId が findNotes と一致しません")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=CSV_FIELDS,
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
        )
        writer.writeheader()
        for note in notes:
            fields = note.get("fields", {})
            writer.writerow(
                {
                    "noteId": note["noteId"],
                    "Text": fields.get("Text", {}).get("value", ""),
                    "Back Extra": fields.get("Back Extra", {}).get("value", ""),
                    "Tags": " ".join(note.get("tags") or []),
                }
            )

    stamp = datetime.now().strftime("%Y%m%d")
    backup_path = OUT_DIR / f"anki_backup_{stamp}.json"
    backup = {
        "deck": DECK_NAME,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note_count": len(notes),
        "notes": notes,
    }
    backup_path.write_text(
        json.dumps(backup, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"exported {len(notes)} notes")
    print(f"csv: {CSV_PATH}")
    print(f"backup: {backup_path}")


if __name__ == "__main__":
    main()

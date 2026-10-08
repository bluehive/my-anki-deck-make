#!/usr/bin/env python3
"""高校数学デッキの Back Extra だけを、noteId 指定で更新する。

既定は --dry-run。--apply を付けたときだけ Anki へ書き込む。
書き込む前に、Anki の Text と Back Extra が anki_export.csv と一致するか確認する。
一致しないノートは更新せず警告する。Text・タグ・学習履歴には触らない。
"""

import argparse
import csv
import sys
from pathlib import Path

import requests

ANKI_CONNECT_URL = "http://localhost:8765"
DECK_NAME = "高校数学・基礎解析"
OUT_DIR = Path("data/math_v2")
EXPORT_CSV = OUT_DIR / "anki_export.csv"
UPDATE_CSV = OUT_DIR / "back_extra_v2.csv"


def invoke(action, params=None):
    payload = {"action": action, "version": 6, "params": params or {}}
    response = requests.post(ANKI_CONNECT_URL, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()
    if result.get("error"):
        raise RuntimeError(f"{action}: {result['error']}")
    return result.get("result")


def require_backup():
    backups = sorted(OUT_DIR.glob("anki_backup_*.json"))
    if not backups:
        print(f"停止: {OUT_DIR}/anki_backup_*.json がありません。先に export_math_from_anki.py を実行してください。")
        raise SystemExit(1)
    return backups[-1]


def load_csv(path, fields):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"{path} が空です")
    missing = [name for name in fields if name not in rows[0]]
    if missing:
        raise SystemExit(f"{path} に列がありません: {missing}")
    return rows


def preview(text, limit=80):
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"


def main():
    parser = argparse.ArgumentParser(description="数学デッキの Back Extra だけを更新する")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="書き込まず差分だけ見る（既定と同じ）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Anki へ書き込む。付けないときは dry-run",
    )
    args = parser.parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--apply と --dry-run は同時に指定できません")
    dry_run = not args.apply

    backup = require_backup()
    export_rows = load_csv(EXPORT_CSV, ["noteId", "Text", "Back Extra"])
    update_rows = load_csv(UPDATE_CSV, ["noteId", "Back Extra"])
    export_by_id = {row["noteId"]: row for row in export_rows}
    update_by_id = {row["noteId"]: row for row in update_rows}
    if set(export_by_id) != set(update_by_id):
        raise SystemExit("noteId が anki_export.csv と back_extra_v2.csv で一致しません")

    note_ids = sorted(int(row["noteId"]) for row in export_rows)
    live_ids = sorted(invoke("findNotes", {"query": f'deck:"{DECK_NAME}"'}) or [])
    if live_ids != note_ids:
        print("警告: Anki の noteId 一覧が anki_export.csv と一致しません。一致するノートだけ処理します。")

    live_notes = invoke("notesInfo", {"notes": note_ids}) or []
    live_by_id = {str(note["noteId"]): note for note in live_notes}

    changed = []
    unchanged = []
    skipped = []
    for note_id in [str(item) for item in note_ids]:
        exported = export_by_id[note_id]
        proposed = update_by_id[note_id]["Back Extra"]
        live = live_by_id.get(note_id)
        if live is None:
            skipped.append((note_id, "Anki にノートがありません"))
            continue
        fields = live.get("fields", {})
        live_text = fields.get("Text", {}).get("value", "")
        live_extra = fields.get("Back Extra", {}).get("value", "")
        if live_text != exported["Text"] or live_extra != exported["Back Extra"]:
            skipped.append((note_id, "書き出し後に Text または Back Extra が変わっています"))
            continue
        if live_extra == proposed:
            unchanged.append(note_id)
            continue
        changed.append((note_id, live_extra, proposed))

    mode = "dry-run" if dry_run else "apply"
    print(f"mode: {mode}")
    print(f"backup: {backup}")
    print(f"対象: {len(note_ids)}  変更: {len(changed)}  変更なし: {len(unchanged)}  スキップ: {len(skipped)}")
    for note_id, reason in skipped:
        print(f"警告: noteId {note_id} は更新しません（{reason}）")

    print("\n先頭3件の差分:")
    for note_id, before, after in changed[:3]:
        print(f"\n--- noteId {note_id} ---")
        print("前:", preview(before, 120))
        print("後:", preview(after, 180))

    if dry_run:
        print("\ndry-run のため書き込みません。書き込むときは --apply を付けます。")
        return

    updated = 0
    for note_id, _before, after in changed:
        # Back Extra だけを送る。Text やタグは payload に入れない。
        invoke(
            "updateNoteFields",
            {"note": {"id": int(note_id), "fields": {"Back Extra": after}}},
        )
        updated += 1
    print(f"\n書き込み完了: {updated} ノート。Text・タグ・学習履歴には触れていません。")


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        print(f"接続エラー: {exc}", file=sys.stderr)
        raise SystemExit(1)

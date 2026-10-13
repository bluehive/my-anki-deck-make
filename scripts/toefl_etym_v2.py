#!/usr/bin/env python3
"""TOEIC 語源・接辞 v2: 裏面だけに表示し、次の100枚を選び、省略を直す。

既定は dry-run。AnkiConnect への書き込みは各サブコマンドに --apply を付けた
ときだけ行う。このファイル自体は書き込みアクションを --apply 以外の経路から
呼ばない。削除系・スケジュール変更系は呼ばない。

選び方の集約は scripts/issue7_etymology.py の aggregate_notes を再利用する。
次の100枚の順位は指示どおり、lapses 降順、同数は最近の失敗が新しい順。
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import issue7_etymology as issue7  # noqa: E402

DATA = REPO / "data" / "toefl_etym_v2"
ISSUE7 = REPO / "data" / "issue7"
BACKUP_PATH = DATA / "backup_before.json"
SELECTED_PATH = DATA / "selected_next100.csv"
HINTS_PATH = DATA / "etymology_v2.csv"

DECK_MEANING = "013TOEIC英単語・意味"
DECK_CONTEXT = "014TOEIC英単語・文脈"
DECKS = (DECK_MEANING, DECK_CONTEXT)
FIELD_NAME = issue7.FIELD_NAME
ETYM_BLOCK = issue7.ETYM_BLOCK
TARGET = 100
# Anki の review id はミリ秒の epoch。これより古い失敗は「最近」に数えない。
# 値そのものは比較用なので、欠測時の順位を最古に固定する。
NO_FAIL_ID = -1

WRITE_ACTIONS = {
    "updateNoteFields",
    "updateNote",
    "updateModelTemplates",
    "updateModelStyling",
    "addNote",
    "addNotes",
    "modelFieldAdd",
    "createModel",
    "deleteNotes",
    "deleteDecks",
    "removeEmptyNotes",
    "modelFieldRemove",
    "modelTemplateRemove",
    "setEaseFactors",
    "setSpecificValueOfCard",
    "forgetCards",
    "relearnCards",
    "setDueDate",
    "answerCards",
    "suspend",
    "unsuspend",
}


def ac(action: str, *, apply: bool = False, **params):
    """AnkiConnect 呼び出し。書き込み系は apply=True のときだけ通す。"""
    if action in WRITE_ACTIONS and not apply:
        raise SystemExit(f"refusing write action without --apply: {action}")
    return issue7.ac(action, **params)


def read_notes(note_ids: list[int]) -> list[dict]:
    notes = []
    for batch in issue7.chunked(note_ids, 100):
        notes.extend(ac("notesInfo", notes=list(batch)))
    return notes


def fetch_deck_rows(deck_name: str) -> list[dict]:
    """issue7.fetch_deck と同じ形。デッキ名だけ v2 の実名を使う。

    issue7.fetch_deck は旧名を DECK_IDS で引くため、ここでは読み取りを複製する。
    スケジュール列は触らない。
    """
    card_ids = ac("findCards", query=f'deck:"{deck_name}"')
    cards = []
    for batch in issue7.chunked(card_ids, 200):
        cards.extend(ac("cardsInfo", cards=list(batch)))
    note_ids = sorted({int(c["note"]) for c in cards})
    notes = {int(n["noteId"]): n for n in read_notes(note_ids)}
    rows = []
    for card in cards:
        model = card["modelName"]
        if model not in issue7.FRONT_FIELDS:
            raise SystemExit(f"unexpected model {model} in {deck_name}")
        note = notes[int(card["note"])]
        front_name = issue7.FRONT_FIELDS[model]
        back_name = issue7.BACK_FIELDS[model]
        rows.append(
            {
                "note_id": int(card["note"]),
                "card_id": int(card["cardId"]),
                "deck_name": deck_name,
                "note_type": model,
                "tags": " ".join(note.get("tags") or []),
                "lapses": int(card["lapses"]),
                "interval": int(card["interval"]),
                "ease_factor": int(card["factor"]),
                "front_or_text": card["fields"][front_name]["value"],
                "back_or_extra": card["fields"][back_name]["value"],
                "etymology": (card["fields"].get(FIELD_NAME) or {}).get("value", ""),
            }
        )
    rows.sort(key=lambda r: (r["note_id"], r["card_id"]))
    return rows


def latest_fail_ids(card_ids: list[int]) -> dict[int, int]:
    """カードごとの最新の失敗（ease=1）の review id。失敗が無ければ NO_FAIL_ID。"""
    out = {int(cid): NO_FAIL_ID for cid in card_ids}
    for batch in issue7.chunked(card_ids, 100):
        reviews = ac("getReviewsOfCards", cards=list(batch)) or {}
        for key, items in reviews.items():
            fails = [int(item["id"]) for item in items if int(item.get("ease", 0)) == 1]
            out[int(key)] = max(fails) if fails else NO_FAIL_ID
    return out


def existing_hint_ids() -> set[int]:
    """語源・接辞が空でないノートと、issue7 の選定100件。"""
    filled = set()
    for model in (issue7.MODEL_BASIC, issue7.MODEL_CLOZE):
        note_ids = ac("findNotes", query=f'note:"{model}"')
        for note in read_notes([int(n) for n in note_ids]):
            value = (note["fields"].get(FIELD_NAME) or {}).get("value", "").strip()
            if value:
                filled.add(int(note["noteId"]))
    selected = issue7.load_selected(ISSUE7 / "selected_notes.csv")
    filled.update(int(row["note_id"]) for row in selected)
    return filled


def select_next(meaning_rows: list[dict], context_rows: list[dict], excluded: set[int]) -> list[dict]:
    """次の100ノート。lapses 降順、同数は最近の失敗が新しい順。

    aggregate_notes は issue7 のものを使う。カードが複数あるノートは lapses を
    合計し、最近の失敗はカードのうち最も新しい失敗 id を採る。
    """
    notes = []
    for rows in (meaning_rows, context_rows):
        fail_ids = latest_fail_ids([row["card_id"] for row in rows])
        for note in issue7.aggregate_notes(rows):
            if note["note_id"] in excluded:
                continue
            latest = max(fail_ids.get(cid, NO_FAIL_ID) for cid in note["card_ids"])
            notes.append({**note, "latest_fail_id": latest, "reason": "lapse-rank"})
    notes.sort(key=lambda n: (-n["lapses"], -n["latest_fail_id"], n["note_id"]))
    chosen = notes[:TARGET]
    if len(chosen) < TARGET:
        raise SystemExit(f"pool smaller than {TARGET}: {len(chosen)}")
    if len({n["note_id"] for n in chosen}) != len(chosen):
        raise SystemExit("duplicate note ids in next selection")
    overlap = {n["note_id"] for n in chosen} & excluded
    if overlap:
        raise SystemExit(f"selection overlapped excluded notes: {sorted(overlap)[:5]}")
    return chosen


def word_of(front: str) -> str:
    """Front / Text から見出し語だけを取る。音声タグと穴埋めは落とす。"""
    text = front.replace("<br>", "\n")
    line = text.split("\n", 1)[0]
    line = line.replace("{{c1::", "").replace("}}", "")
    return line.strip()


def write_selected(path: Path, selected: list[dict]) -> None:
    columns = [
        "note_id",
        "deck_name",
        "note_type",
        "reason",
        "lapses",
        "latest_fail_id",
        "interval",
        "ease_factor",
        "front_or_text",
        "word",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for note in selected:
            writer.writerow({**note, "word": word_of(note["front_or_text"])})


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def strip_block(text: str) -> str:
    """ETYM_BLOCK と、その直前の改行を全部落とす。"""
    cleaned = text
    while ETYM_BLOCK in cleaned:
        at = cleaned.find(ETYM_BLOCK)
        start = at
        if start > 0 and cleaned[start - 1] == "\n":
            start -= 1
        cleaned = cleaned[:start] + cleaned[at + len(ETYM_BLOCK) :]
    return cleaned


def transform_templates(templates: dict, model_name: str) -> dict:
    """Front から語源ブロックを除き、Back の解答の後にちょうど1回置く。

    Basic は {{Back}} の後。Cloze は既存の本文（hr が無いので本文の後）に1回。
    戻り値は新しい dict。入力は変えない。
    """
    out = {}
    for name, sides in templates.items():
        front = strip_block(sides.get("Front", ""))
        back = strip_block(sides.get("Back", ""))
        if FIELD_NAME in front or ETYM_BLOCK in front:
            raise SystemExit(f"{model_name}/{name} front still mentions the field")
        if model_name == issue7.MODEL_BASIC:
            if "{{Back}}" not in back:
                raise SystemExit(f"{model_name}/{name} back lost {{{{Back}}}}")
            back = back.rstrip() + "\n\n" + ETYM_BLOCK
        else:
            # Cloze already keeps the block after the answer text. Do not add a blank line.
            back = back.rstrip() + "\n" + ETYM_BLOCK
        if back.count(ETYM_BLOCK) != 1:
            raise SystemExit(f"{model_name}/{name} back does not contain the block once")
        out[name] = {"Front": front, "Back": back}
    return out


def unified(before: str, after: str, label: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{label} (before)",
            tofile=f"{label} (after)",
        )
    )


def classify_hints(rows: list[dict], current: dict[int, str]) -> dict[str, list[dict]]:
    """etymology_v2.csv の行を新規 / 修正 / 変更なしに分ける。"""
    groups = {"new": [], "revised": [], "unchanged": []}
    for row in rows:
        nid = int(row["note_id"])
        hint = row["hint"]
        before = current.get(nid)
        item = {"note_id": nid, "before": before if before is not None else "", "after": hint}
        if before is None or before.strip() == "":
            groups["new"].append(item)
        elif before != hint:
            groups["revised"].append(item)
        else:
            groups["unchanged"].append(item)
    return groups


def field_payload(note_id: int, hint: str) -> dict:
    """updateNoteFields に渡す形。フィールドは語源・接辞だけ。"""
    return {"id": note_id, "fields": {FIELD_NAME: hint}}


def cmd_backup(_args) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    decks = ac("deckNames")
    for name in DECKS:
        if name not in decks:
            raise SystemExit(f"profile does not contain {name}")
    payload = {"decks": {}, "models": {}}
    for name in DECKS:
        rows = fetch_deck_rows(name)
        notes = {}
        for row in rows:
            notes[str(row["note_id"])] = {
                "note_type": row["note_type"],
                "front_or_text": row["front_or_text"],
                "back_or_extra": row["back_or_extra"],
                "語源・接辞": row["etymology"],
            }
        payload["decks"][name] = {"note_count": len(notes), "notes": notes}
    for model in (issue7.MODEL_BASIC, issue7.MODEL_CLOZE):
        payload["models"][model] = {
            "templates": ac("modelTemplates", modelName=model),
            "styling": ac("modelStyling", modelName=model),
            "fields": ac("modelFieldNames", modelName=model),
        }
    BACKUP_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"backup={BACKUP_PATH}")
    for name, deck in payload["decks"].items():
        print(f"{name} notes={deck['note_count']}")


def cmd_templates(args) -> None:
    for model in (issue7.MODEL_BASIC, issue7.MODEL_CLOZE):
        before = ac("modelTemplates", modelName=model)
        after = transform_templates(before, model)
        for name in before:
            print(unified(before[name].get("Front", ""), after[name]["Front"], f"{model}/{name}/Front"))
            print(unified(before[name].get("Back", ""), after[name]["Back"], f"{model}/{name}/Back"))
        if args.apply:
            ac("updateModelTemplates", apply=True, model={"name": model, "templates": after})
            print(f"applied templates {model}")
        else:
            print(f"dry-run templates {model}: not written")


def cmd_select(_args) -> None:
    meaning = fetch_deck_rows(DECK_MEANING)
    context = fetch_deck_rows(DECK_CONTEXT)
    excluded = existing_hint_ids()
    selected = select_next(meaning, context, excluded)
    write_selected(SELECTED_PATH, selected)
    print(f"excluded={len(excluded)}")
    print(f"selected={len(selected)}")
    print(f"path={SELECTED_PATH}")
    print(
        "lapses_range="
        f"{selected[-1]['lapses']}..{selected[0]['lapses']}"
    )


def cmd_fields(args) -> None:
    rows = load_csv(HINTS_PATH)
    wanted = [int(row["note_id"]) for row in rows]
    current = {}
    for note in read_notes(wanted):
        nid = int(note["noteId"])
        current[nid] = (note["fields"].get(FIELD_NAME) or {}).get("value", "")
    groups = classify_hints(rows, current)
    print(f"新規{len(groups['new'])}件／修正{len(groups['revised'])}件／変更なし{len(groups['unchanged'])}件")
    for label, key in (("新規", "new"), ("修正", "revised")):
        for item in groups[key]:
            print(f"{label} {item['note_id']}")
            print(f"  - {item['before']}")
            print(f"  + {item['after']}")
    if args.apply:
        for row in rows:
            payload = field_payload(int(row["note_id"]), row["hint"])
            if set(payload["fields"]) != {FIELD_NAME}:
                raise SystemExit(f"payload fields are not etymology-only: {payload}")
            ac("updateNoteFields", apply=True, note=payload)
        print(f"applied={len(rows)}")
    else:
        print("dry-run fields: not written")


def main() -> None:
    parser = argparse.ArgumentParser(description="TOEIC etymology hints v2 (dry-run by default)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup")
    templates = sub.add_parser("templates")
    templates.add_argument("--apply", action="store_true")
    sub.add_parser("select")
    fields = sub.add_parser("fields")
    fields.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    {
        "backup": cmd_backup,
        "templates": cmd_templates,
        "select": cmd_select,
        "fields": cmd_fields,
    }[args.cmd](args)


if __name__ == "__main__":
    main()

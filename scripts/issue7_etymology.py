#!/usr/bin/env python3
"""Issue #7: export TOEIC decks, select ~100 notes, add a non-graded
etymology field, and verify scheduling is unchanged.

Reads and writes notes only through AnkiConnect. Scheduling columns that
AnkiConnect's cardsInfo does not return (odue, odid) are snapshotted from a
read-only copy of the collection. This script never opens the live database
for writing and never calls scheduling-changing actions.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ANKI_URL = "http://127.0.0.1:8765"
COLLECTION = Path(
    "/home/mevius/.var/app/net.ankiweb.Anki/data/Anki2/Game/collection.anki2"
)
REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "issue7"

DECK_MEANING = "TOEIC英単語・意味"
DECK_CONTEXT = "TOEIC英単語・文脈"
DECK_IDS = {
    DECK_MEANING: 1783553808215,
    DECK_CONTEXT: 1783557424181,
}
MODEL_BASIC = "Basic"
MODEL_CLOZE = "Cloze"
MODEL_IDS = {MODEL_BASIC: 1351748277749, MODEL_CLOZE: 1642207253876}
FIELD_NAME = "語源・接辞"
TARGET = 100

FRONT_FIELDS = {MODEL_BASIC: "Front", MODEL_CLOZE: "Text"}
BACK_FIELDS = {MODEL_BASIC: "Back", MODEL_CLOZE: "Back Extra"}

SCHED_KEYS = (
    "type",
    "queue",
    "due",
    "ivl",
    "factor",
    "reps",
    "lapses",
    "left",
    "odue",
    "odid",
)
# cardsInfo names that differ from the SQLite column names.
CARDSINFO_MAP = {"ivl": "interval"}

ETYM_BLOCK = (
    "{{#語源・接辞}}<div class=\"etym-hint\">語源・接辞: {{語源・接辞}}</div>{{/語源・接辞}}"
)
CSS_SNIPPET = (
    "\n.etym-hint {\n"
    " font-size: 0.72em;\n"
    " line-height: 1.35;\n"
    " color: #555;\n"
    " margin-top: 0.8em;\n"
    " text-align: left;\n"
    "}\n"
    ".nightMode .etym-hint { color: #aaa; }\n"
)


def ac(action: str, **params):
    payload = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    req = urllib.request.Request(
        ANKI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"AnkiConnect unreachable for {action}: {exc}") from exc
    if data.get("error"):
        raise SystemExit(f"AnkiConnect error on {action}: {data['error']}")
    return data.get("result")


def chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def snapshot_scheduling(dest: Path) -> dict[int, dict]:
    """Read-only snapshot of scheduling for every Basic and Cloze card.

    Copies the collection (including WAL) so the live file is never opened
    for a write, then reads type/queue/due/ivl/factor/reps/lapses/left/odue/odid.
    """
    snap_dir = Path("/tmp/anki-issue7-sched-snap")
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    snap_dir.mkdir(parents=True)
    shutil.copy2(COLLECTION, snap_dir / "collection.anki2")
    for suffix in ("-wal", "-shm"):
        src = Path(str(COLLECTION) + suffix)
        if src.exists():
            shutil.copy2(src, snap_dir / f"collection.anki2{suffix}")
    con = sqlite3.connect(f"file:{snap_dir / 'collection.anki2'}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    model_ids = tuple(MODEL_IDS.values())
    rows = con.execute(
        """
        SELECT c.id, c.nid, c.type, c.queue, c.due, c.ivl, c.factor,
               c.reps, c.lapses, c.left, c.odue, c.odid, n.mid
        FROM cards c
        JOIN notes n ON n.id = c.nid
        WHERE n.mid IN (?, ?)
        ORDER BY c.id
        """,
        model_ids,
    ).fetchall()
    con.close()
    out = {}
    with dest.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["card_id", "note_id", "model_id", *SCHED_KEYS])
        for row in rows:
            card_id = int(row[0])
            note_id = int(row[1])
            sched = {
                "type": int(row[2]),
                "queue": int(row[3]),
                "due": int(row[4]),
                "ivl": int(row[5]),
                "factor": int(row[6]),
                "reps": int(row[7]),
                "lapses": int(row[8]),
                "left": int(row[9]),
                "odue": int(row[10]),
                "odid": int(row[11]),
            }
            model_id = int(row[12])
            out[card_id] = {"note_id": note_id, "model_id": model_id, **sched}
            writer.writerow([card_id, note_id, model_id, *[sched[k] for k in SCHED_KEYS]])
    return out


def load_scheduling(path: Path) -> dict[int, dict]:
    out = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            card_id = int(row["card_id"])
            out[card_id] = {
                "note_id": int(row["note_id"]),
                "model_id": int(row["model_id"]),
                **{k: int(row[k]) for k in SCHED_KEYS},
            }
    return out


def fetch_deck(deck_name: str) -> list[dict]:
    card_ids = ac("findCards", query=f'deck:"{deck_name}"')
    cards = []
    for batch in chunked(card_ids, 200):
        cards.extend(ac("cardsInfo", cards=batch))
    note_ids = sorted({int(c["note"]) for c in cards})
    notes = {}
    for batch in chunked(note_ids, 200):
        for note in ac("notesInfo", notes=batch):
            notes[int(note["noteId"])] = note
    rows = []
    for card in cards:
        model = card["modelName"]
        if model not in FRONT_FIELDS:
            raise SystemExit(f"unexpected model {model} in {deck_name}")
        note = notes[int(card["note"])]
        tags = note.get("tags") or []
        front_name = FRONT_FIELDS[model]
        back_name = BACK_FIELDS[model]
        rows.append(
            {
                "note_id": int(card["note"]),
                "card_id": int(card["cardId"]),
                "deck_id": DECK_IDS[deck_name],
                "deck_name": deck_name,
                "note_type": model,
                "tags": " ".join(tags),
                "lapses": int(card["lapses"]),
                "interval": int(card["interval"]),
                "ease_factor": int(card["factor"]),
                "front_or_text": card["fields"][front_name]["value"],
                "back_or_extra": card["fields"][back_name]["value"],
                "type": int(card["type"]),
                "queue": int(card["queue"]),
                "due": int(card["due"]),
                "reps": int(card["reps"]),
                "left": int(card["left"]),
            }
        )
    rows.sort(key=lambda r: (r["note_id"], r["card_id"]))
    return rows


def write_export(path: Path, rows: list[dict]) -> None:
    columns = [
        "note_id",
        "card_id",
        "deck_id",
        "deck_name",
        "note_type",
        "tags",
        "lapses",
        "interval",
        "ease_factor",
        "front_or_text",
        "back_or_extra",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in columns})


def aggregate_notes(rows: list[dict]) -> list[dict]:
    """One record per note. lapses summed; interval and factor are minima."""
    grouped: dict[int, dict] = {}
    for row in rows:
        nid = row["note_id"]
        cur = grouped.get(nid)
        if cur is None:
            grouped[nid] = {
                "note_id": nid,
                "deck_name": row["deck_name"],
                "note_type": row["note_type"],
                "lapses": row["lapses"],
                "interval": row["interval"],
                "ease_factor": row["ease_factor"],
                "front_or_text": row["front_or_text"],
                "back_or_extra": row["back_or_extra"],
                "card_ids": [row["card_id"]],
            }
        else:
            cur["lapses"] += row["lapses"]
            cur["interval"] = min(cur["interval"], row["interval"])
            cur["ease_factor"] = min(cur["ease_factor"], row["ease_factor"])
            cur["card_ids"].append(row["card_id"])
            if row["front_or_text"] != cur["front_or_text"]:
                raise SystemExit(f"note {nid} has differing front fields across cards")
    return list(grouped.values())


def select_notes(meaning_rows: list[dict], context_rows: list[dict]) -> list[dict]:
    meaning = aggregate_notes(meaning_rows)
    context = aggregate_notes(context_rows)
    selected = []
    seen = set()
    for note in meaning + context:
        if note["lapses"] >= 1:
            if note["note_id"] in seen:
                raise SystemExit(f"duplicate note id in lapse set: {note['note_id']}")
            seen.add(note["note_id"])
            selected.append({**note, "reason": "lapse"})
    # Stable order for the lapse set: not required, but keep deck then note id.
    selected.sort(key=lambda n: (0 if n["deck_name"] == DECK_MEANING else 1, n["note_id"]))
    remaining = TARGET - len(selected)
    if remaining > 0:
        pool = [n for n in meaning if n["note_id"] not in seen]
        pool.sort(key=lambda n: (n["interval"], n["ease_factor"], n["note_id"]))
        for note in pool[:remaining]:
            seen.add(note["note_id"])
            selected.append({**note, "reason": "fill"})
    if len(selected) > TARGET:
        raise SystemExit(f"selection exceeded {TARGET}: {len(selected)}")
    if len({n["note_id"] for n in selected}) != len(selected):
        raise SystemExit("duplicate note ids in selection")
    return selected


def write_selected(path: Path, selected: list[dict]) -> None:
    columns = [
        "note_id",
        "deck_name",
        "note_type",
        "reason",
        "lapses",
        "interval",
        "ease_factor",
        "front_or_text",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for note in selected:
            writer.writerow(note)


def load_selected(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_hints(path: Path) -> dict[int, str]:
    hints = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            nid = int(row["note_id"])
            hint = row["hint"].strip()
            if not hint or "TODO" in hint or hint.lower() == "xxx":
                raise SystemExit(f"empty or placeholder hint for {nid}")
            if nid in hints:
                raise SystemExit(f"duplicate hint note id {nid}")
            hints[nid] = hint
    return hints


def ensure_field(model_name: str) -> str:
    fields = ac("modelFieldNames", modelName=model_name)
    if FIELD_NAME in fields:
        return "already-present"
    if fields[-1] == FIELD_NAME:
        return "already-present"
    ac("modelFieldAdd", modelName=model_name, fieldName=FIELD_NAME)
    fields_after = ac("modelFieldNames", modelName=model_name)
    if fields_after[-1] != FIELD_NAME:
        raise SystemExit(f"{model_name} field was not appended at the end: {fields_after}")
    if fields_after[:-1] != fields:
        raise SystemExit(f"{model_name} existing fields changed: {fields} -> {fields_after}")
    return "added"


def ensure_template(model_name: str) -> str:
    templates = ac("modelTemplates", modelName=model_name)
    changed = False
    for name, sides in templates.items():
        front = sides.get("Front", "")
        back = sides.get("Back", "")
        if "{{Front}}" not in front and "{{cloze:Text}}" not in front and "cloze:Text" not in front:
            raise SystemExit(f"{model_name}/{name} front lost its graded placeholder:\n{front}")
        if ETYM_BLOCK not in front:
            sides["Front"] = front.rstrip() + "\n" + ETYM_BLOCK
            changed = True
        if "{{FrontSide}}" in back:
            continue
        if ETYM_BLOCK not in back:
            sides["Back"] = back.rstrip() + "\n" + ETYM_BLOCK
            changed = True
    if changed:
        ac("updateModelTemplates", model={"name": model_name, "templates": templates})
        return "updated"
    return "unchanged"


def ensure_css(model_name: str) -> str:
    styling = ac("modelStyling", modelName=model_name)
    css = styling["css"]
    if ".etym-hint" in css:
        return "already-present"
    ac("updateModelStyling", model={"name": model_name, "css": css.rstrip() + CSS_SNIPPET})
    return "added"


def apply_hints(hints: dict[int, str]) -> int:
    # This AnkiConnect build accepts updateNoteFields(note=...), not notes=[...].
    # Each payload contains only the etymology field.
    updated = 0
    for nid, hint in hints.items():
        ac("updateNoteFields", note={"id": nid, "fields": {FIELD_NAME: hint}})
        updated += 1
    return updated


def content_map(rows: list[dict]) -> dict[int, tuple[str, str]]:
    out = {}
    for row in rows:
        out[row["note_id"]] = (row["front_or_text"], row["back_or_extra"])
    return out


def verify(before_sched: dict[int, dict], selected_ids: set[int], before_content: dict[int, tuple[str, str]]) -> dict:
    after_path = DATA / "scheduling_after.csv"
    after_sched = snapshot_scheduling(after_path)
    diffs = []
    for card_id, before in before_sched.items():
        after = after_sched.get(card_id)
        if after is None:
            diffs.append({"card_id": card_id, "problem": "missing-after", "before": before, "after": None})
            continue
        for key in SCHED_KEYS:
            if before[key] != after[key]:
                diffs.append(
                    {
                        "card_id": card_id,
                        "problem": "changed",
                        "field": key,
                        "before": before[key],
                        "after": after[key],
                    }
                )
    extra_after = sorted(set(after_sched) - set(before_sched))
    if extra_after:
        diffs.append({"problem": "extra-cards-after", "card_ids": extra_after[:20], "count": len(extra_after)})

    # Cross-check the cardsInfo-visible subset against the before snapshot too.
    basic_ids = ac("findCards", query=f'note:"{MODEL_BASIC}"')
    cloze_ids = ac("findCards", query=f'note:"{MODEL_CLOZE}"')
    # "note:" is a note-type search in Anki. Confirm via model later if needed.
    info_diffs = []
    live_cards = []
    for batch in chunked(basic_ids + cloze_ids, 200):
        live_cards.extend(ac("cardsInfo", cards=batch))
    for card in live_cards:
        card_id = int(card["cardId"])
        if card["modelName"] not in (MODEL_BASIC, MODEL_CLOZE):
            continue
        before = before_sched.get(card_id)
        if before is None:
            info_diffs.append({"card_id": card_id, "problem": "cardsInfo-not-in-snapshot"})
            continue
        live = {
            "type": int(card["type"]),
            "queue": int(card["queue"]),
            "due": int(card["due"]),
            "ivl": int(card["interval"]),
            "factor": int(card["factor"]),
            "reps": int(card["reps"]),
            "lapses": int(card["lapses"]),
            "left": int(card["left"]),
        }
        for key, value in live.items():
            if before[key] != value:
                info_diffs.append(
                    {
                        "card_id": card_id,
                        "problem": "cardsInfo-mismatch",
                        "field": key,
                        "before": before[key],
                        "after": value,
                    }
                )

    meaning = fetch_deck(DECK_MEANING)
    context = fetch_deck(DECK_CONTEXT)
    after_content = content_map(meaning + context)
    content_diffs = []
    for nid, before_pair in before_content.items():
        after_pair = after_content.get(nid)
        if after_pair != before_pair:
            content_diffs.append({"note_id": nid, "before": before_pair, "after": after_pair})

    # Anki 26 rejects a bare `field:_*` search ("colon without a keyword").
    # Count non-empty values from notesInfo instead of that query.
    filled = []
    outside = []
    missing = []
    for model in (MODEL_BASIC, MODEL_CLOZE):
        note_ids = ac("findNotes", query=f'note:"{model}"')
        for batch in chunked(note_ids, 200):
            for note in ac("notesInfo", notes=batch):
                value = (note["fields"].get(FIELD_NAME) or {}).get("value", "").strip()
                nid = int(note["noteId"])
                if nid in selected_ids:
                    if value:
                        filled.append(nid)
                    else:
                        missing.append(nid)
                elif value:
                    outside.append(nid)

    return {
        "scheduling_diffs": diffs,
        "cardsinfo_diffs": info_diffs,
        "content_diffs": content_diffs,
        "field_filled": len(set(filled)),
        "filled_ids": sorted(set(filled)),
        "outside_filled": outside,
        "missing_selected": missing,
        "meaning_rows": len(meaning),
        "context_rows": len(context),
        "basic_cards_snap": sum(1 for v in before_sched.values() if v["model_id"] == MODEL_IDS[MODEL_BASIC]),
        "cloze_cards_snap": sum(1 for v in before_sched.values() if v["model_id"] == MODEL_IDS[MODEL_CLOZE]),
        "after_cards": len(after_sched),
    }


def write_verification(path: Path, selected: list[dict], report: dict) -> None:
    lapse_n = sum(1 for n in selected if n["reason"] == "lapse")
    fill_n = sum(1 for n in selected if n["reason"] == "fill")
    sched_ok = not report["scheduling_diffs"] and not report["cardsinfo_diffs"]
    content_ok = not report["content_diffs"]
    field_ok = (
        report["field_filled"] == len(selected)
        and not report["outside_filled"]
        and not report["missing_selected"]
    )
    lines = [
        "# Issue #7 検証",
        "",
        "## 主張",
        "",
        f"選定 {len(selected)} ノートだけに非採点フィールド「語源・接辞」が入り、"
        "採点本文とスケジューリングは変わっていない。"
        if sched_ok and content_ok and field_ok
        else "検証は不一致あり。PR は作らない。",
        "",
        "## データ",
        "",
        f"- 意味デッキ CSV 行数: {report['meaning_rows']}",
        f"- 文脈デッキ CSV 行数: {report['context_rows']}",
        f"- lapse 由来: {lapse_n}",
        f"- fill 由来: {fill_n}",
        f"- 選定合計: {len(selected)}",
        f"- フィールド投入数（空でない）: {report['field_filled']}",
        f"- 選定外で空でないノート: {len(report['outside_filled'])}",
        f"- 選定のうち空のまま: {len(report['missing_selected'])}",
        f"- 本文一致: {'yes' if content_ok else 'no'}",
        f"- スケジューリング一致: {'yes' if sched_ok else 'no'}",
        f"- Basic+Cloze カード数（書き込み前スナップショット）: {len(report['scheduling_diffs']) and 'see diffs' or report['after_cards']}",
        f"- Basic カード（スナップショット）: {report['basic_cards_snap']}",
        f"- Cloze カード（スナップショット）: {report['cloze_cards_snap']}",
        "",
        "## 論拠",
        "",
        "Anki はカードのスケジューリング列（type, queue, due, ivl, factor, reps, lapses, left, odue, odid）が"
        "一致していれば復習履歴を動かしていない。cardsInfo は odue/odid を返さないため、"
        "その2列はコレクションの読み取り専用コピーから控え、残りは cardsInfo とも突き合わせた。"
        "updateNoteFields は語源・接辞だけを payload に入れたので、Front/Back/Text/Back Extra が"
        "書き込み前と一致すれば採点本文は残っている。条件ブロックはフィールドが空のとき描画されないため、"
        "選定外デッキの見た目は変わらない。",
        "",
        "## パス",
        "",
        "- data/issue7/toeic_meaning_export.csv",
        "- data/issue7/toeic_context_export.csv",
        "- data/issue7/selected_notes.csv",
        "- data/issue7/etymology.csv",
        "- data/issue7/scheduling_before.csv",
        "- data/issue7/scheduling_after.csv",
        "",
    ]
    if report["scheduling_diffs"] or report["cardsinfo_diffs"]:
        lines.append("## スケジューリング差分")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(
            {"sqlite": report["scheduling_diffs"][:50], "cardsInfo": report["cardsinfo_diffs"][:50]},
            ensure_ascii=False,
            indent=2,
        ))
        lines.append("```")
        lines.append("")
    if report["content_diffs"]:
        lines.append("## 本文差分")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(report["content_diffs"][:20], ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    if report["outside_filled"] or report["missing_selected"]:
        lines.append("## フィールド不一致")
        lines.append("")
        lines.append(f"- outside: {report['outside_filled'][:50]}")
        lines.append(f"- missing: {report['missing_selected'][:50]}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_export(_args) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    decks = ac("deckNames")
    for name in (DECK_MEANING, DECK_CONTEXT):
        if name not in decks:
            raise SystemExit(f"profile does not contain {name}; decks={decks}")
    meaning = fetch_deck(DECK_MEANING)
    context = fetch_deck(DECK_CONTEXT)
    write_export(DATA / "toeic_meaning_export.csv", meaning)
    write_export(DATA / "toeic_context_export.csv", context)
    selected = select_notes(meaning, context)
    write_selected(DATA / "selected_notes.csv", selected)
    before = snapshot_scheduling(DATA / "scheduling_before.csv")
    before_content = content_map(meaning + context)
    (DATA / "content_before.json").write_text(
        json.dumps({str(k): v for k, v in before_content.items()}, ensure_ascii=False),
        encoding="utf-8",
    )
    lapse_n = sum(1 for n in selected if n["reason"] == "lapse")
    fill_n = sum(1 for n in selected if n["reason"] == "fill")
    print(f"meaning_rows={len(meaning)}")
    print(f"context_rows={len(context)}")
    print(f"meaning_notes={len(aggregate_notes(meaning))}")
    print(f"context_notes={len(aggregate_notes(context))}")
    print(f"lapse_notes={lapse_n}")
    print(f"fill_notes={fill_n}")
    print(f"selected_total={len(selected)}")
    print(f"sched_cards={len(before)}")
    models = sorted({n["note_type"] for n in selected})
    print(f"selected_models={models}")


def cmd_prepare_models(_args) -> None:
    selected = load_selected(DATA / "selected_notes.csv")
    models = sorted({row["note_type"] for row in selected})
    for model in models:
        print(f"field {model}: {ensure_field(model)}")
        print(f"template {model}: {ensure_template(model)}")
        print(f"css {model}: {ensure_css(model)}")
        print("fields now", ac("modelFieldNames", modelName=model))


def cmd_apply(_args) -> None:
    selected = load_selected(DATA / "selected_notes.csv")
    hints = load_hints(DATA / "etymology.csv")
    selected_ids = {int(row["note_id"]) for row in selected}
    if set(hints) != selected_ids:
        missing = sorted(selected_ids - set(hints))
        extra = sorted(set(hints) - selected_ids)
        raise SystemExit(f"hint set mismatch missing={missing[:10]} extra={extra[:10]}")
    for hint in hints.values():
        if len(hint) > 80:
            raise SystemExit(f"hint longer than 80: {hint}")
    updated = apply_hints(hints)
    print(f"updated={updated}")


def cmd_verify(_args) -> None:
    selected = load_selected(DATA / "selected_notes.csv")
    selected_ids = {int(row["note_id"]) for row in selected}
    before = load_scheduling(DATA / "scheduling_before.csv")
    raw = json.loads((DATA / "content_before.json").read_text(encoding="utf-8"))
    before_content = {int(k): tuple(v) for k, v in raw.items()}
    report = verify(before, selected_ids, before_content)
    write_verification(DATA / "verification.md", selected, report)
    sched_ok = not report["scheduling_diffs"] and not report["cardsinfo_diffs"]
    print(f"field_filled={report['field_filled']}")
    print(f"outside={len(report['outside_filled'])}")
    print(f"missing={len(report['missing_selected'])}")
    print(f"content_diffs={len(report['content_diffs'])}")
    print(f"scheduling_unchanged={'yes' if sched_ok else 'no'}")
    print(f"sched_diffs={len(report['scheduling_diffs'])}")
    print(f"cardsinfo_diffs={len(report['cardsinfo_diffs'])}")
    if not sched_ok:
        print(json.dumps(report["scheduling_diffs"][:10], ensure_ascii=False))
        print(json.dumps(report["cardsinfo_diffs"][:10], ensure_ascii=False))
        raise SystemExit(2)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export")
    sub.add_parser("prepare-models")
    sub.add_parser("apply")
    sub.add_parser("verify")
    args = parser.parse_args()
    {"export": cmd_export, "prepare-models": cmd_prepare_models, "apply": cmd_apply, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()

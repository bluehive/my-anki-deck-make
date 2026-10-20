#!/usr/bin/env python3
"""Issue #16 の「学ぶ順番」9枚を、AnkiConnect なしで確認する。"""

from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "metacog_deck.csv"
CANON_PATH = Path("/home/mevius/handoff-to-goose/anki_issue16_metacog_cards.csv")
CATEGORY = "学ぶ順番"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adder = load_module("metacog_issue16_add", ROOT / "scripts" / "metacog_issue16_add.py")


def read_csv_rows(path: Path = CSV_PATH):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def canon_rows():
    return read_csv_rows(CANON_PATH)


class FakeAnki:
    """findNotes / notesInfo だけを返し、書き込み系は記録する。実 Anki には繋がない。"""

    def __init__(self, fronts: list[str] | None = None):
        self.notes = {1000 + i: front for i, front in enumerate(fronts or [])}
        self.next_id = max(self.notes, default=1000) + 1
        self.calls = []

    def __call__(self, action, params=None):
        self.calls.append((action, params))
        params = params or {}
        if action == "findNotes":
            query = params["query"]
            front = query.split('"Front:', 1)[1]
            if front.endswith('"'):
                front = front[:-1]
            return [note_id for note_id, value in self.notes.items() if value == front]
        if action == "notesInfo":
            return [
                {"noteId": note_id, "fields": {"Front": {"value": self.notes[note_id]}}}
                for note_id in params["notes"]
                if note_id in self.notes
            ]
        if action == "addNote":
            note_id = self.next_id
            self.next_id += 1
            self.notes[note_id] = params["note"]["fields"]["Front"]
            return note_id
        if action in {"updateNoteFields", "deleteNotes"}:
            return None
        raise AssertionError(action)


def actions_of(calls) -> list[str]:
    return [action for action, _params in calls]


def write_actions_of(calls) -> list[str]:
    return [action for action in actions_of(calls) if action in adder.WRITE_ACTIONS]


def new_cards():
    return adder.load_new_cards(CSV_PATH)


def test_csv_has_47_rows_and_new_nine_match_canon():
    rows = read_csv_rows()
    assert len(rows) == 47
    assert list(rows[0].keys()) == ["表面", "裏面", "カテゴリ"]
    new_rows = [row for row in rows if row["カテゴリ"] == CATEGORY]
    assert new_rows == canon_rows()
    assert len(new_rows) == 9
    assert [row["表面"] for row in rows[-9:]] == [row["表面"] for row in new_rows]


def test_dry_run_writes_nothing():
    fake = FakeAnki()
    plan = adder.plan_addition(new_cards(), invoke_fn=fake)
    assert len(plan["adds"]) == 9
    assert plan["skips"] == []
    assert plan["updates"] == []
    assert plan["deletes"] == []
    assert write_actions_of(fake.calls) == []
    assert "addNote" not in actions_of(fake.calls)
    assert "updateNoteFields" not in actions_of(fake.calls)
    assert "deleteNotes" not in actions_of(fake.calls)


def test_apply_adds_nine_and_never_updates_or_deletes():
    fake = FakeAnki()
    plan = adder.plan_addition(new_cards(), invoke_fn=fake)
    before = len(fake.calls)
    result = adder.apply_plan(plan, invoke_fn=fake)
    assert result == {"added": 9, "updated": 0, "deleted": 0}
    written = write_actions_of(fake.calls[before:])
    assert written == ["addNote"] * 9
    assert "updateNoteFields" not in actions_of(fake.calls)
    assert "deleteNotes" not in actions_of(fake.calls)


def test_rerun_adds_zero():
    fake = FakeAnki()
    first = adder.plan_addition(new_cards(), invoke_fn=fake)
    adder.apply_plan(first, invoke_fn=fake)
    before = len(fake.calls)
    second = adder.plan_addition(new_cards(), invoke_fn=fake)
    result = adder.apply_plan(second, invoke_fn=fake)
    assert second["adds"] == []
    assert len(second["skips"]) == 9
    assert result == {"added": 0, "updated": 0, "deleted": 0}
    assert write_actions_of(fake.calls[before:]) == []
    assert "updateNoteFields" not in actions_of(fake.calls)
    assert "deleteNotes" not in actions_of(fake.calls)


def test_partial_existing_adds_only_the_rest():
    cards = new_cards()
    already = [cards[0]["front"], cards[3]["front"], cards[8]["front"]]
    fake = FakeAnki(already)
    plan = adder.plan_addition(cards, invoke_fn=fake)
    assert [item["front"] for item in plan["adds"]] == [
        card["front"] for card in cards if card["front"] not in already
    ]
    assert len(plan["adds"]) == 6
    assert len(plan["skips"]) == 3
    result = adder.apply_plan(plan, invoke_fn=fake)
    assert result == {"added": 6, "updated": 0, "deleted": 0}
    assert "updateNoteFields" not in actions_of(fake.calls)
    assert "deleteNotes" not in actions_of(fake.calls)
    again = adder.plan_addition(cards, invoke_fn=fake)
    assert again["adds"] == []


def test_cli_dry_run_default_does_not_apply(monkeypatch, capsys):
    called = {"apply": 0}

    def forbid_apply(*_args, **_kwargs):
        called["apply"] += 1
        raise AssertionError("dry-run で apply_plan が呼ばれた")

    monkeypatch.setattr(
        adder,
        "plan_addition",
        lambda *_args, **_kwargs: {
            "deck": "02メタ認知アップ",
            "adds": [{"front": "「分散学習」とは？", "back": "x", "category": CATEGORY}],
            "skips": [],
            "updates": [],
            "deletes": [],
        },
    )
    monkeypatch.setattr(adder, "apply_plan", forbid_apply)
    assert adder.main([]) == 0
    assert called["apply"] == 0
    captured = capsys.readouterr().out
    assert "dry-run" in captured
    assert "追加予定: 1件" in captured

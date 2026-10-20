#!/usr/bin/env python3
"""メタ認知デッキの分割（Issue #14）を、AnkiConnect なしで確認する。"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "metacog_deck.csv"
MAPPING_PATH = ROOT / "data" / "metacog_split" / "mapping.json"

CHUNKS = [
    (
        "自分で学びを回す「自己調整学習」の3つの要素は？",
        "メタ認知・学び方（学習方略）・やる気（動機づけ）。",
        "基本のことば",
    ),
    (
        "失敗の原因を分ける3つのラベルは？",
        "知識不足・手順ミス・状態（体調や環境）。",
        "失敗したとき",
    ),
    (
        "自信のもとになる4つのものは？",
        "①自分でできた経験 ②似た人の成功を見る ③理由のある励まし ④体や気持ちの状態。",
        "自信の育て方",
    ),
]

EXPECTED_CATEGORIES = {
    "基本のことば": 7,
    "自信の育て方": 6,
    "失敗したとき": 5,
    "分かったつもり対策": 4,
    "自分への質問": 3,
    "説明して覚える": 4,
    "毎日の実践": 9,
    "学ぶ順番": 9,
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = load_module("generate_metacog_deck", ROOT / "generate_metacog_deck.py")
importer = load_module("import_to_anki", ROOT / "import_to_anki.py")
migrate = load_module("metacog_split_migrate", ROOT / "scripts" / "metacog_split_migrate.py")


def read_csv_rows():
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def mapping():
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


def test_csv_shape_and_uniqueness():
    rows = read_csv_rows()
    assert len(rows) == 47
    assert list(rows[0].keys()) == ["表面", "裏面", "カテゴリ"]
    fronts = [row["表面"] for row in rows]
    assert len(fronts) == len(set(fronts))
    for row in rows:
        assert row["裏面"].strip()
        assert len(row["裏面"]) <= gen.BACK_MAX_LEN


def test_old_fronts_gone_and_chunks_kept():
    rows = read_csv_rows()
    by_front = {row["表面"]: row for row in rows}
    rewritten = 0
    for split in mapping()["splits"]:
        star = split["cards"][0]
        # 表面を変えた元カードは残さない。表面を維持する★は裏面だけ新しい文言にする。
        if star["front"] != split["old_front"]:
            assert split["old_front"] not in by_front
            rewritten += 1
        else:
            assert by_front[split["old_front"]]["裏面"] == star["back"]
            assert by_front[split["old_front"]]["裏面"] != split["old_back"]
        for card in split["cards"]:
            assert by_front[card["front"]]["裏面"] == card["back"]
            assert by_front[card["front"]]["カテゴリ"] == card["category"]
    assert rewritten == 3
    for front, back, category in CHUNKS:
        assert by_front[front]["裏面"] == back
        assert by_front[front]["カテゴリ"] == category


def test_generator_matches_csv_and_counts():
    assert gen.EXPECTED_TOTAL == 47
    assert importer.METACOG_EXPECTED_COUNT == 47
    assert importer.METACOG_EXPECTED_COUNT == gen.EXPECTED_TOTAL
    rows = read_csv_rows()
    generated = [
        {"表面": front, "裏面": back, "カテゴリ": category}
        for front, back, category in gen.CARDS
    ]
    assert rows == generated
    counts = {}
    for row in rows:
        counts[row["カテゴリ"]] = counts.get(row["カテゴリ"], 0) + 1
    assert counts == EXPECTED_CATEGORIES


def test_mapping_star_is_first_and_counts_add_eight():
    splits = mapping()["splits"]
    assert len(splits) == 5
    added = 0
    for split in splits:
        assert split["cards"][0]["front"]
        added += len(split["cards"]) - 1
    assert added == 8


class FakeAnki:
    """findNotes / notesInfo だけを返し、書き込み系は記録する。

    notes の値は表面の文字列か、{"front", "back"} のどちらか。
    裏面を渡さない既存テストでは Back を返さず、再書き込み判定を従来どおりにする。
    """

    def __init__(self, notes: dict[int, str | dict]):
        self.notes = {note_id: self._entry(value) for note_id, value in notes.items()}
        self.next_id = max(self.notes, default=1000) + 1
        self.calls = []

    @staticmethod
    def _entry(value):
        if isinstance(value, dict):
            return {"front": value["front"], "back": value.get("back")}
        return {"front": value, "back": None}

    def __call__(self, action, params=None):
        self.calls.append(action)
        params = params or {}
        if action == "findNotes":
            query = params["query"]
            front = query.split('"Front:', 1)[1]
            if front.endswith('"'):
                front = front[:-1]
            return [
                note_id
                for note_id, entry in self.notes.items()
                if entry["front"] == front
            ]
        if action == "notesInfo":
            infos = []
            for note_id in params["notes"]:
                entry = self.notes.get(note_id)
                if entry is None:
                    continue
                fields = {"Front": {"value": entry["front"]}}
                if entry["back"] is not None:
                    fields["Back"] = {"value": entry["back"]}
                infos.append({"noteId": note_id, "fields": fields})
            return infos
        if action == "updateNoteFields":
            note = params["note"]
            entry = self.notes.setdefault(note["id"], {"front": "", "back": None})
            entry["front"] = note["fields"]["Front"]
            if "Back" in note["fields"]:
                entry["back"] = note["fields"]["Back"]
            return None
        if action == "addNote":
            note_id = self.next_id
            self.next_id += 1
            fields = params["note"]["fields"]
            self.notes[note_id] = {"front": fields["Front"], "back": fields.get("Back")}
            return note_id
        if action == "deleteNotes":
            return None
        raise AssertionError(action)


def old_notes():
    data = mapping()
    return {100 + i: split["old_front"] for i, split in enumerate(data["splits"], start=1)}


def write_actions(fake: FakeAnki):
    return [action for action in fake.calls if action in migrate.WRITE_ACTIONS]


def test_dry_run_does_not_write():
    fake = FakeAnki(old_notes())
    plan = migrate.plan_migration(mapping(), invoke_fn=fake)
    assert len(plan["updates"]) == 5
    assert len(plan["adds"]) == 8
    assert plan["skips"] == []
    assert write_actions(fake) == []
    assert "updateNoteFields" not in fake.calls
    assert "addNote" not in fake.calls
    assert "deleteNotes" not in fake.calls


def test_apply_updates_five_and_adds_eight():
    fake = FakeAnki(old_notes())
    plan = migrate.plan_migration(mapping(), invoke_fn=fake)
    before = list(fake.calls)
    result = migrate.apply_plan(plan, invoke_fn=fake)
    assert result == {"updated": 5, "added": 8, "deleted": 0}
    written = [action for action in fake.calls[len(before) :] if action in migrate.WRITE_ACTIONS]
    assert written.count("updateNoteFields") == 5
    assert written.count("addNote") == 8
    assert written.count("deleteNotes") == 0
    for item in plan["updates"]:
        assert fake.notes[item["note_id"]]["front"] == item["new_front"]


def test_apply_is_idempotent_when_already_migrated():
    data = mapping()
    notes = {}
    note_id = 200
    for split in data["splits"]:
        for card in split["cards"]:
            notes[note_id] = card["front"]
            note_id += 1
    fake = FakeAnki(notes)
    plan = migrate.plan_migration(data, invoke_fn=fake)
    # 表面を維持した★は再実行でも同じ noteId を上書きするだけ。追加はしない。
    assert plan["adds"] == []
    assert {item["id"] for item in plan["updates"]} == {"3", "5"}
    result = migrate.apply_plan(plan, invoke_fn=fake)
    assert result["added"] == 0
    assert result["deleted"] == 0
    assert "addNote" not in fake.calls
    assert "deleteNotes" not in fake.calls
    again = migrate.plan_migration(data, invoke_fn=fake)
    assert again["adds"] == []


def test_duplicate_source_notes_are_skipped():
    notes = old_notes()
    duplicated = mapping()["splits"][0]["old_front"]
    notes[999] = duplicated
    fake = FakeAnki(notes)
    plan = migrate.plan_migration(mapping(), invoke_fn=fake)
    skipped = [item for item in plan["skips"] if item["old_front"] == duplicated]
    assert len(skipped) == 1
    assert skipped[0]["count"] == 2
    assert all(item["id"] != "1" for item in plan["updates"])
    assert all(item["id"] != "1" for item in plan["adds"])
    assert "updateNoteFields" not in fake.calls
    assert "addNote" not in fake.calls
    assert "deleteNotes" not in fake.calls


def test_cli_dry_run_default_does_not_apply(monkeypatch, capsys):
    called = {"apply": 0}

    def forbid_apply(*_args, **_kwargs):
        called["apply"] += 1
        raise AssertionError("dry-run で apply_plan が呼ばれた")

    monkeypatch.setattr(migrate, "plan_migration", lambda *_args, **_kwargs: {
        "deck": "02メタ認知アップ",
        "updates": [],
        "adds": [],
        "skips": [],
    })
    monkeypatch.setattr(migrate, "apply_plan", forbid_apply)
    assert migrate.main([]) == 0
    assert called["apply"] == 0
    assert "dry-run" in capsys.readouterr().out


def test_add_note_tags_match_existing_importer():
    tags = migrate.note_tags("毎日の実践")
    assert tags == ["metacog", importer.PROJECT_TAG, "毎日の実践"]


def partial_migrated_notes():
    """★は更新済み。追加カードは各分割の先頭1枚だけ残し、残りは未追加にする。"""
    notes = {}
    note_id = 300
    for split in mapping()["splits"]:
        star = split["cards"][0]
        notes[note_id] = {"front": star["front"], "back": star["back"]}
        note_id += 1
        first_extra = split["cards"][1]
        notes[note_id] = {"front": first_extra["front"], "back": first_extra["back"]}
        note_id += 1
    return notes


def test_resume_after_partial_add_adds_only_the_rest():
    fake = FakeAnki(partial_migrated_notes())
    plan = migrate.plan_migration(mapping(), invoke_fn=fake)
    assert plan["updates"] == []
    assert len(plan["adds"]) == 3
    assert {item["id"] for item in plan["adds"]} == {"1", "3"}
    result = migrate.apply_plan(plan, invoke_fn=fake)
    assert result == {"updated": 0, "added": 3, "deleted": 0}
    assert "updateNoteFields" not in fake.calls
    assert "deleteNotes" not in fake.calls


def test_second_run_after_resume_writes_nothing():
    fake = FakeAnki(partial_migrated_notes())
    first = migrate.plan_migration(mapping(), invoke_fn=fake)
    migrate.apply_plan(first, invoke_fn=fake)
    before = list(fake.calls)
    second = migrate.plan_migration(mapping(), invoke_fn=fake)
    result = migrate.apply_plan(second, invoke_fn=fake)
    assert second["updates"] == []
    assert second["adds"] == []
    assert result == {"updated": 0, "added": 0, "deleted": 0}
    written = [action for action in fake.calls[len(before) :] if action in migrate.WRITE_ACTIONS]
    assert written == []

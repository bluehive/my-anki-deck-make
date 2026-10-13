#!/usr/bin/env python3
"""語源・接辞 v2 のテンプレート変換と CSV を、AnkiConnect なしで確認する。"""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "toefl_etym_v2"
ISSUE7 = ROOT / "data" / "issue7"

spec = importlib.util.spec_from_file_location(
    "toefl_etym_v2", ROOT / "scripts" / "toefl_etym_v2.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def elements(hint: str) -> list[str]:
    parts, buf, depth = [], "", 0
    for ch in hint:
        if ch == "（":
            depth += 1
            buf += ch
        elif ch == "）":
            depth = max(0, depth - 1)
            buf += ch
        elif ch == "+" and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def load_backup_templates():
    backup = json.loads((DATA / "backup_before.json").read_text(encoding="utf-8"))
    return backup["models"]


def test_front_loses_etymology_and_back_keeps_one():
    models = load_backup_templates()
    for model_name in ("Basic", "Cloze"):
        before = models[model_name]["templates"]
        after = mod.transform_templates(before, model_name)
        assert after, model_name
        for name, sides in after.items():
            assert "語源・接辞" not in sides["Front"], (model_name, name, sides["Front"])
            assert sides["Back"].count(mod.ETYM_BLOCK) == 1
            # open, label, field, close.
            assert sides["Back"].count("語源・接辞") == 4
            assert mod.ETYM_BLOCK in sides["Back"]
            if model_name == "Basic":
                assert sides["Back"].index("{{Back}}") < sides["Back"].index(mod.ETYM_BLOCK)
            assert sides["Front"].strip() in ("{{Front}}", "{{edit:cloze:Text}}")


def test_back_block_count_is_exactly_one():
    models = load_backup_templates()
    for model_name in ("Basic", "Cloze"):
        after = mod.transform_templates(models[model_name]["templates"], model_name)
        for sides in after.values():
            assert sides["Back"].count("{{#語源・接辞}}") == 1
            assert sides["Back"].count("{{/語源・接辞}}") == 1
            assert "語源・接辞" not in sides["Front"]


def test_selected_next100_is_disjoint_from_existing():
    selected = list(csv.DictReader((DATA / "selected_next100.csv").open(encoding="utf-8")))
    existing = {row["note_id"] for row in csv.DictReader((ISSUE7 / "selected_notes.csv").open(encoding="utf-8"))}
    ids = [row["note_id"] for row in selected]
    assert len(selected) == 100
    assert len(set(ids)) == 100
    assert not (set(ids) & existing)


def test_hints_cover_new_notes_and_gloss_every_element():
    hints = list(csv.DictReader((DATA / "etymology_v2.csv").open(encoding="utf-8")))
    selected = {row["note_id"] for row in csv.DictReader((DATA / "selected_next100.csv").open(encoding="utf-8"))}
    hint_ids = [row["note_id"] for row in hints]
    assert len(hint_ids) == len(set(hint_ids))
    assert selected <= set(hint_ids)
    for row in hints:
        hint = row["hint"]
        assert "…" not in hint
        assert "..." not in hint
        for part in elements(hint):
            assert "（" in part.split("。")[0], (row["note_id"], part)


def test_dry_run_does_not_call_write_actions(monkeypatch, capsys):
    calls = []
    rows = [
        {"note_id": "1", "hint": "a（意味）"},
        {"note_id": "2", "hint": "b（意味）"},
        {"note_id": "3", "hint": "same"},
    ]

    def fake_ac(action, *, apply=False, **params):
        calls.append((action, apply))
        assert action == "notesInfo"
        return [
            {"noteId": 1, "fields": {"語源・接辞": {"value": ""}}},
            {"noteId": 2, "fields": {"語源・接辞": {"value": "old"}}},
            {"noteId": 3, "fields": {"語源・接辞": {"value": "same"}}},
        ]

    monkeypatch.setattr(mod, "load_csv", lambda path: rows)
    monkeypatch.setattr(mod, "ac", fake_ac)
    mod.cmd_fields(argparse_namespace(apply=False))
    out = capsys.readouterr().out
    assert calls == [("notesInfo", False)]
    assert "新規1件／修正1件／変更なし1件" in out
    assert "dry-run fields: not written" in out


def test_write_payload_contains_only_the_etymology_field():
    payload = mod.field_payload(1783554462533, "aud-（聞く）+ -ence（状態・性質の名詞）")
    assert set(payload) == {"id", "fields"}
    assert set(payload["fields"]) == {"語源・接辞"}
    assert payload["id"] == 1783554462533


def test_apply_refuses_without_flag():
    with pytest.raises(SystemExit, match="without --apply"):
        mod.ac("updateNoteFields", note={"id": 1, "fields": {"語源・接辞": "x"}})


class argparse_namespace:
    def __init__(self, apply):
        self.apply = apply

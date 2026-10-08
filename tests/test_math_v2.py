#!/usr/bin/env python3
"""back_extra_v2.csv が export と整合し、追記ルールを守っているか確認する。"""

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "data/math_v2/anki_export.csv"
UPDATE = ROOT / "data/math_v2/back_extra_v2.csv"
MIN_LEN = 150
MAX_LEN = 450
# 追記（【なぜ成り立つ？】以降）の \\( \\) の外に残ってはいけない TeX。
BARE_TEX = re.compile(r"\^|_{|\\frac|\\sqrt|\\log|\\pi|\\theta")


def load(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    export_rows = load(EXPORT)
    update_rows = load(UPDATE)
    errors = []
    length_out = []

    if len(update_rows) != 100:
        errors.append(f"行数が 100 ではありません: {len(update_rows)}")
    if [row["noteId"] for row in update_rows] != [row["noteId"] for row in export_rows]:
        errors.append("noteId が anki_export.csv と一致しません")

    for index, (old, new) in enumerate(zip(export_rows, update_rows), 1):
        extra = new["Back Extra"]
        if not extra.startswith(old["Back Extra"]):
            errors.append(f"{index}: 旧 Back Extra で始まっていません")
        if "{{c" in extra:
            errors.append(f"{index}: {{{{c を含みます")
        left = extra.count("\\(")
        right = extra.count("\\)")
        if left != right:
            errors.append(f"{index}: \\( が {left}、\\) が {right}")
        if not (MIN_LEN <= len(extra) <= MAX_LEN):
            length_out.append((index, new["noteId"], len(extra)))
        marker = "【なぜ成り立つ？】"
        addition_at = extra.find(marker)
        if addition_at < 0:
            errors.append(f"{index}: 追記の見出しがありません")
            continue
        addition = extra[addition_at:]
        outside = re.sub(r"\\\(.*?\\\)", "", addition, flags=re.DOTALL)
        if BARE_TEX.search(outside):
            errors.append(f"{index}: 追記の \\(...\\) の外に TeX 記法が残っています")

    print(f"notes: {len(update_rows)}")
    print(f"noteId match: {not any('noteId' in item for item in errors)}")
    print(f"length out of {MIN_LEN}-{MAX_LEN}: {len(length_out)}")
    for index, note_id, length in length_out:
        print(f"  #{index} noteId={note_id} length={length}")
    if errors:
        print("FAILED")
        for item in errors:
            print(f"  {item}")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

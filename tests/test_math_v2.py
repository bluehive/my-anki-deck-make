#!/usr/bin/env python3
"""back_extra_v2.csv が export と整合し、追記の MathJax が崩れていないか確認する。"""

import csv
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "data/math_v2/anki_export.csv"
UPDATE = ROOT / "data/math_v2/back_extra_v2.csv"
MIN_LEN = 150
MAX_LEN = 450
MARKER = "【なぜ成り立つ？】"
MATH = re.compile(r"\\\((.*?)\\\)", re.DOTALL)
# \( \) の外に残してはいけない、数式らしい断片。
BARE_CARET = re.compile(r"\^")
BARE_UNDERSCORE = re.compile(r"_")
BARE_ROOT = re.compile(r"√|\\sqrt")
BARE_SLASH_FRACTION = re.compile(r"\d\s*/\s*\d")
BARE_FRAC = re.compile(r"\\frac")
# \( \) の中に残してはいけない、バックスラッシュのない関数名と log_数字。
BARE_FUNCTION = re.compile(r"(?<!\\)(?:sin|cos|tan|log|ln)\b")
BARE_LOG_DIGIT = re.compile(r"(?<!\\)log_\d|\\log_\d")


def load(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def addition_of(extra):
    at = extra.find(MARKER)
    if at < 0:
        return None
    return extra[at:]


def katex_runtime():
    """KaTeX を実行する command と env。リポジトリにはパッケージを入れない。

    使えないときは (None, None)。呼び出し側は「未実施」と記録する。
    """
    if shutil.which("node") is None:
        return None, None
    local = subprocess.run(
        ["node", "-e", "require('katex')"],
        capture_output=True,
        text=True,
    )
    if local.returncode == 0:
        return ["node"], None
    if shutil.which("npm") is None:
        return None, None
    install_dir = Path("/tmp/anki-math-katex")
    marker = install_dir / "node_modules" / "katex" / "package.json"
    if not marker.is_file():
        install_dir.mkdir(parents=True, exist_ok=True)
        installed = subprocess.run(
            ["npm", "install", "--silent", "--prefix", str(install_dir), "katex"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if installed.returncode != 0 or not marker.is_file():
            return None, None
    env = dict(os.environ)
    node_path = str(install_dir / "node_modules")
    if env.get("NODE_PATH"):
        node_path = node_path + ":" + env["NODE_PATH"]
    env["NODE_PATH"] = node_path
    return ["node"], env


def check_katex(bodies):
    """各 \\( \\) の中身を KaTeX で構文チェックする。使えないときは None。"""
    command, env = katex_runtime()
    if command is None:
        return None
    script = r"""
const katex = require("katex");
const bodies = JSON.parse(process.argv[1]);
const bad = [];
bodies.forEach((body, index) => {
  try {
    katex.renderToString(body, {throwOnError: true});
  } catch (error) {
    bad.push([index, String(error.message).split("\n")[0]]);
  }
});
process.stdout.write(JSON.stringify(bad));
"""
    result = subprocess.run(
        command + ["-e", script, json.dumps(bodies, ensure_ascii=False)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env=env,
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def main():
    export_rows = load(EXPORT)
    update_rows = load(UPDATE)
    errors = []
    length_out = []
    katex_bodies = []
    katex_where = []

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
        if extra.count("\\(") != extra.count("\\)"):
            errors.append(f"{index}: \\( と \\) の数が違います")
        if not (MIN_LEN <= len(extra) <= MAX_LEN):
            length_out.append((index, new["noteId"], len(extra)))
        addition = addition_of(extra)
        if addition is None:
            errors.append(f"{index}: 追記の見出しがありません")
            continue
        for match in MATH.finditer(addition):
            body = match.group(1)
            katex_bodies.append(body)
            katex_where.append(index)
            if body.count("(") != body.count(")"):
                errors.append(f"{index}: \\(...\\) の () が合いません: {body}")
            if body.count("{") != body.count("}"):
                errors.append(f"{index}: \\(...\\) の {{}} が合いません: {body}")
            if BARE_FUNCTION.search(body):
                errors.append(f"{index}: \\(...\\) に \\ のない関数名があります: {body}")
            if BARE_LOG_DIGIT.search(body):
                errors.append(f"{index}: \\(...\\) に log_数字 があります: {body}")
        outside = MATH.sub("", addition)
        if BARE_CARET.search(outside) or BARE_UNDERSCORE.search(outside):
            errors.append(f"{index}: \\(...\\) の外に ^ または _ があります")
        if BARE_ROOT.search(outside):
            errors.append(f"{index}: \\(...\\) の外に √ または \\sqrt があります")
        if BARE_SLASH_FRACTION.search(outside):
            errors.append(f"{index}: \\(...\\) の外に 数字/数字 があります")
        if BARE_FRAC.search(outside):
            errors.append(f"{index}: \\(...\\) の外に \\frac があります")

    katex_errors = check_katex(katex_bodies)
    if katex_errors is None:
        print("KaTeX: 未実施（node から katex を読めません）")
    else:
        print(f"KaTeX: {len(katex_bodies)} 式を検査")
        for position, message in katex_errors:
            errors.append(f"{katex_where[position]}: KaTeX: {message}")

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

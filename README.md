# my-anki-deck-make

Anki 向け学習デッキ（**227問**）を CSV 生成し、[AnkiConnect](https://foosoft.net/projects/anki-connect/) 経由で自動インポートする Python プロジェクトです。

> **コード・ビルド**: [Grok](https://grok.com)（xAI）が生成・整備しました。

## デッキ一覧

| デッキ名 | 問数 | 形式 | CSV |
|----------|------|------|-----|
| Git学習 | 50 | Basic + ミニマル画像 | `git_deck.csv` |
| 高校数学・基礎解析 | 100 | Cloze + MathJax + 解説 | `math_deck.csv` |
| Emacsキー操作 | 77 | Basic | `emacs_deck.csv` |
| 02メタ認知アップ | 48 | Cloze | `metacog_deck.csv` |

## 必要環境

- Python 3.10+
- [Anki](https://apps.ankiweb.net/)（インポート時）
- [AnkiConnect](https://foosoft.net/projects/anki-connect/) アドオン（コード: `2055492159`）

## セットアップ

```bash
pip install -r requirements.txt
```

## CSV の再生成

```bash
python generate_git_deck.py
python generate_math_deck.py
python generate_emacs_deck.py
python generate_metacog_deck.py
```

## Anki へのインポート

Anki を起動し、AnkiConnect を有効にした状態で実行します。

```bash
# 全デッキ
python import_to_anki.py

# 個別
python import_to_anki.py --git-only
python import_to_anki.py --math-only
python import_to_anki.py --emacs-only
python import_to_anki.py --metacog-only

# 事前チェックのみ（Anki 不要）
python import_to_anki.py --preflight

# 数学デッキの Text / 解説を CSV から同期
python import_to_anki.py --fix-mathjax
```

## プロジェクト構成

```
my-anki-deck-make/
├── git_deck.csv / math_deck.csv / emacs_deck.csv / metacog_deck.csv
├── generate_*.py          # 各デッキ CSV 生成
├── math_explanations.py   # 数学デッキ解説（Back Extra）
├── import_to_anki.py      # AnkiConnect インポート
├── assets/images/git-deck/  # Git デッキ用画像（50枚）
├── plan.md                # 仕様・設計ドキュメント
└── requirements.txt
```

## 数学デッキの数式について

- 数式は Anki 標準の **MathJax** 記法 `\(...\)` を使用します（MiKTeX 不要）
- Cloze と MathJax の併用時は `}}` と `\)` の衝突を避けるため、Cloze 終了前にスペースを入れています
- 条件注記（例: `a ≥ 0`）は表面表示のため Unicode 表記を使用しています

## License

MIT License — 詳細は [LICENSE](LICENSE) を参照してください。
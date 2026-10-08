# 依頼: Anki「高校数学・基礎解析」の Back Extra（解説）を厚くする

依頼元: ウカイ（Grok Bot 経由）。監視: Grok Bot。PR はユーザー承認後に rebase マージ。
**このタスクはゴールが明確なので確認質問なしで進めてよい。**

## 背景（Grok Bot 調査済み）
- Anki デッキ `高校数学・基礎解析`: Cloze ノート 100 件。フィールドは `Text` / `Back Extra` / `語源・接辞`。
- ユーザーは Anki 上で数枚を手で直している（noteId 昇順で 4,5,8,14,15,20,22,26,27,28,30,35,40,43,44,67,68,74,85,100 番目の Text、24,39 番目などの Back Extra）。
- **したがって、Anki 上の現在値が正。リポジトリの `math_deck.csv` は正ではない。**
- 既存の `import_to_anki.py --fix-mathjax` は CSV で Text と Back Extra を上書きする。そのため、このタスクでは**絶対に実行しない**。
- AnkiConnect は http://localhost:8765 で稼働中。

## 作業ブランチ
`cd ~/my-project/my-anki-deck-make && git checkout main && git pull && git checkout -b feat/math-back-extra-v2`
この指示書を `docs/math-back-extra-v2-spec.md` としてコミットする。

## 仕様
### 1. 書き出し `export_math_from_anki.py`（読み取り専用）
- AnkiConnect の `findNotes`（`deck:"高校数学・基礎解析"`）と `notesInfo` を使い、noteId 昇順で取得する。
- `data/math_v2/anki_export.csv` に書き出す。列は `noteId,Text,Back Extra,Tags`。値は Anki の生 HTML のまま（`&gt;` や `<br>` を変換しない）。全列クォート、UTF-8。
- 同じ内容を JSON にもする。全フィールドとタグを `data/math_v2/anki_backup_YYYYMMDD.json` に保存し、バックアップとする。

### 2. 解説を厚くする `data/math_v2/back_extra_v2.csv`
- 列は `noteId,Back Extra`。100 行。
- **今の Back Extra（ユーザー修正を含む）を先頭に一字一句そのまま残す。** その後ろに `<br><br>` で区切って追記する。
- 追記の形式（HTML、改行は `<br>`）:
  - `【なぜ成り立つ？】` 1〜2文で導き方や直感を書く。
  - `【例題】` 具体的な数値で、途中式つきの1問。
  - `【よくあるミス】` 1つ。
  - （任意）`【関連】` つながる公式を1つ。
- 数式は MathJax の `\( ... \)` を使ってよい。`{{c` は使わない。`\(` と `\)` の数は必ず釣り合わせる。
- 1枚あたりの合計の長さは 150〜450 文字が目安。高校生が読める言葉で書く。
- 数学的な正しさを最優先する。自信がない項目は deepseek-flash に相談して確認する。
- カードの内容（Text）に合わせて書く。Text を読んで、何を問うカードかを確認してから書く。

### 3. 書き戻し `update_math_back_extra.py`
- 既定は `--dry-run` で、変更件数と先頭3件の差分を表示するだけ。`--apply` を付けたときだけ書き込む。
- 書き込む前に、Anki の今の Text と Back Extra が `anki_export.csv` と同じか確認する。違うノートは更新せず、警告を出す（書き出したあとのユーザーの編集を守るため）。
- `updateNoteFields` で **`Back Extra` だけ**を noteId 指定で更新する。Text、タグ、学習履歴には触らない。ノートの削除や再作成はしない。
- 実行前に `anki_backup_*.json` が存在しなければ止まる。

### 4. 検証 `tests/test_math_v2.py`（または同等のスクリプト）
- back_extra_v2.csv が 100 行で、noteId が export と完全に一致すること。
- 各行が旧 Back Extra で始まること。
- `{{c` を含まないこと。`\(` と `\)` の数が等しいこと。
- 長さが 150〜450 文字であること（超えたものは一覧にして PR に書く）。

### 5. リポジトリ側の整合
- `math_explanations.py` の 100 件を新しい解説に更新する（`<br>` は `\n` に戻す。noteId 昇順とリストの順は一致している）。
- `generate_math_deck.py` を実行して `math_deck.csv` の Extra を再生成する。Text はこのタスクでは変えない。
- README の `--fix-mathjax` の説明に注意を書き足す。「Anki 上で問題文を手で直している場合、CSV の内容で上書きされる。解説の更新には `update_math_back_extra.py` を使う」。

## 手順
1. ブランチを作り、仕様書をコミットする。
2. 書き出しを実行する（Anki は読み取りのみ）。export とバックアップをコミットする。
3. 解説を書き、検証を通す。
4. `update_math_back_extra.py --dry-run` を実行し、結果を記録する。**`--apply` はまだ実行しない**（ユーザー承認後に Grok Bot が実行する）。
5. `git push -u origin feat/math-back-extra-v2` のあと、`gh pr create --base main` で PR を作る。本文は三角ロジック（主張/データ/論拠）で書く。データには dry-run の結果と検証結果、解説の例を3枚分（変更前と変更後）載せる。マージはしない。
6. 最後に PR URL、検証結果、dry-run の結果を出力する。

## 禁止
- `--fix-mathjax` の実行、`--apply` の実行、Anki のノート削除、デッキ削除。
- `~/GoogleDrive/Private/` に触れること。素の pip（Python は mise 経由の uv）。

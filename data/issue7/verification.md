# Issue #7 検証

## 主張

選定 100 ノートだけに非採点フィールド「語源・接辞」が入り、採点本文とスケジューリングは変わっていない。

## データ

- 意味デッキ CSV 行数: 1062
- 文脈デッキ CSV 行数: 1042
- lapse 由来: 16
- fill 由来: 84
- 選定合計: 100
- フィールド投入数（空でない）: 100
- 選定外で空でないノート: 0
- 選定のうち空のまま: 0
- 本文一致: yes
- スケジューリング一致: yes
- Basic+Cloze カード数（書き込み前スナップショット）: 2461
- Basic カード（スナップショット）: 1218
- Cloze カード（スナップショット）: 1243

## 論拠

Anki はカードのスケジューリング列（type, queue, due, ivl, factor, reps, lapses, left, odue, odid）が一致していれば復習履歴を動かしていない。cardsInfo は odue/odid を返さないため、その2列はコレクションの読み取り専用コピーから控え、残りは cardsInfo とも突き合わせた。updateNoteFields は語源・接辞だけを payload に入れたので、Front/Back/Text/Back Extra が書き込み前と一致すれば採点本文は残っている。条件ブロックはフィールドが空のとき描画されないため、選定外デッキの見た目は変わらない。

## パス

- data/issue7/toeic_meaning_export.csv
- data/issue7/toeic_context_export.csv
- data/issue7/selected_notes.csv
- data/issue7/etymology.csv
- data/issue7/scheduling_before.csv
- data/issue7/scheduling_after.csv

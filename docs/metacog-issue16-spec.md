# メタ認知デッキ Issue #16 追加仕様（分散学習と交互練習）

Refs #16

## 目的
デッキ「02メタ認知アップ」に新カテゴリ「学ぶ順番」の Basic カード9枚を追加する（38→47）。

## データ
- 正本: `anki_issue16_metacog_cards.csv`（列 表面/裏面/カテゴリ）。文言は一字一句変更しない。
- `generate_metacog_deck.py` に9枚を末尾追加し、`metacog_deck.csv` を再生成（ヘッダ除き47行）。
- `import_to_anki.py`: `METACOG_EXPECTED_COUNT = 47`。

## 移行スクリプト `scripts/metacog_issue16_add.py`
- 既定は dry-run（追加予定を表示のみ）。`--apply` で実行。
- デッキ「02メタ認知アップ」に表面が既存でないカードのみ addNote。
- 既存38ノートの更新・削除は一切しない（updateNoteFields/deleteNotes を呼ばない）。
- 冪等: 2回目の `--apply` は追加0件。
- `scripts/metacog_split_migrate.py` のパターン（AnkiConnect 呼び出し）に倣う。

## テスト
- fake AnkiConnect で: dry-run は書き込みなし／apply で9件追加／再実行で0件／一部既存なら残りのみ／更新・削除APIを呼ばない。
- CSV 47行・新9枚が正本と一致。

#!/usr/bin/env python3
"""IDで数学ノートの表示フィールドだけを更新する。既定は差分確認。"""
import argparse
import hashlib
import csv
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/math_mobile'
DECK = '019 高校数学・基礎解析'


def invoke(action, params=None):
    request = Request('http://localhost:8765', data=json.dumps({
        'action': action, 'version': 6, 'params': params or {}
    }).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result['error']:
        raise RuntimeError(result['error'])
    return result['result']


def load(name):
    with (DATA / name).open(encoding='utf-8', newline='') as handle:
        rows = list(csv.DictReader(handle))
    result = {int(row['noteId']): row for row in rows}
    if len(result) != len(rows):
        raise RuntimeError('CSVに重複IDがあります')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='承認後に既存ノートへ適用')
    parser.add_argument('--deck', default=DECK)
    args = parser.parse_args()
    before = {int(k): v for k, v in json.loads((DATA / 'baseline.json').read_text()).items()}
    after = load('mobile.csv')
    ids = sorted(invoke('findNotes', {'query': f'deck:"{args.deck}"'}))
    if set(ids) != set(before) or set(before) != set(after):
        raise RuntimeError('対象デッキとCSVのID集合が一致しません。更新を中止します')
    live = {note['noteId']: note for note in invoke('notesInfo', {'notes': ids})}
    pending = []
    for note_id in ids:
        actual = {key: live[note_id]['fields'][key]['value'] for key in ('Text', 'Back Extra')}
        desired = {key: after[note_id][key] for key in actual}
        actual_hash = hashlib.sha256(json.dumps(actual, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if actual == desired:
            continue
        if actual_hash != before[note_id]:
            raise RuntimeError(f'{note_id}: 書き出し後に内容が変わっています。更新を中止します')
        pending.append((note_id, desired))
    print(f'{len(ids)} ノート照合済み、更新予定 {len(pending)} 件')
    if not args.apply:
        print('差分確認のみ。承認後に --apply を指定してください')
        return
    # 全件の事前照合後に更新。ノート・カード作成、タグ、テンプレート、履歴の変更はしない。
    for note_id, fields in pending:
        invoke('updateNoteFields', {'note': {'id': note_id, 'fields': fields}})
    checked = invoke('notesInfo', {'notes': ids})
    for note in checked:
        for key in ('Text', 'Back Extra'):
            if note['fields'][key]['value'] != after[note['noteId']][key]:
                raise RuntimeError(f"更新後の確認に失敗: {note['noteId']} / {key}")
    print('全ノートの更新と再読込確認が完了しました')


if __name__ == '__main__':
    main()

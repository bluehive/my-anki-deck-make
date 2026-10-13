import contextlib
import hashlib
import json
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_mobile', ROOT / 'scripts/sync_math_mobile.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncMobileTests(unittest.TestCase):
    def setUp(self):
        self.after = sync.load('mobile.csv')
        self.ids = sorted(self.after)
        self.before = {i: {'Text': 'original text', 'Back Extra': 'original extra', 'Tags': self.after[i]['Tags']} for i in self.ids}
        self.baseline = {str(i): hashlib.sha256(json.dumps({k:self.before[i][k] for k in ('Text','Back Extra')},ensure_ascii=False,sort_keys=True).encode()).hexdigest() for i in self.ids}
        self.notes = [{'noteId': i, 'fields': {k: {'value': self.before[i][k]}
                      for k in ('Text', 'Back Extra')}} for i in self.ids]
        self.writes = []

    def invoke(self, action, params=None):
        if action == 'findNotes':
            return self.ids
        if action == 'notesInfo':
            return self.notes
        self.writes.append((action, params))
        raise AssertionError('dry-run must not write')

    def run_sync(self):
        with patch.object(sync, 'invoke', self.invoke), patch.object(sync.json, 'loads', return_value=self.baseline), patch('sys.argv', ['sync']), contextlib.redirect_stdout(io.StringIO()):
            sync.main()

    def test_dry_run_preserves_live_notes(self):
        self.run_sync()
        self.assertEqual(self.writes, [])

    def test_reject_changed_note_before_any_write(self):
        self.notes[-1]['fields']['Text']['value'] += 'ユーザー編集'
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.writes, [])

    def test_reject_missing_id(self):
        self.ids = self.ids[:-1]
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.writes, [])

    def test_already_applied_can_be_rerun(self):
        for note in self.notes:
            for key in note['fields']:
                note['fields'][key]['value'] = self.after[note['noteId']][key]
        self.run_sync()
        self.assertEqual(self.writes, [])

    def test_identity_and_cloze_preserved(self):
        self.assertEqual(len(self.before), 100)
        self.assertEqual(set(self.before), set(self.after))
        for i in self.before:
            self.assertEqual(self.before[i]['Tags'], self.after[i]['Tags'])
            self.assertEqual(self.after[i]['Text'].count('{{c1::'), 1)
            self.assertNotIn('{{c2::', self.after[i]['Text'])


if __name__ == '__main__':
    unittest.main()

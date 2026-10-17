import json
import hashlib
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from recovery import chunks_for, parse_source, scan, review, packet, digest


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / '.codex/sessions/a.jsonl'
        self.source.parent.mkdir(parents=True)
        self.work = self.root / 'work'

    def tearDown(self):
        self.tmp.cleanup()

    def write_rows(self, rows):
        self.source.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))

    def message(self, text):
        return {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                                   'content': [{'type': 'input_text', 'text': text}]}}

    def test_legacy_and_modern_preserve_repeated_utterances(self):
        self.write_rows([{'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': '同意'}]},
                         self.message('同意')])
        parsed = parse_source(self.source, 'codex')
        self.assertEqual(len(parsed['turns']), 2)
        self.assertEqual(len(parsed['formats']), 2)

    def test_chunks_cover_long_text_without_loss(self):
        text = 'abcdef' * 3300
        chunks = chunks_for([{'id': '1', 'role': 'user', 'time': '', 'text': text}])
        self.assertEqual(''.join(p['text'] for c in chunks for p in c['parts']), text)

    def test_invalid_or_unknown_blocks_block_review_completion(self):
        self.source.write_text('{bad}\n' + json.dumps(self.message('hello')) + '\n' +
                              json.dumps({'type': 'message', 'role': 'user', 'content': [{'type': 'unknown'}]}))
        self.assertEqual(len(parse_source(self.source, 'codex')['errors']), 2)

    def test_unicode_separator_is_inside_json_string(self):
        self.write_rows([self.message('本人の発言\u2028続き\u2029終わり')])
        parsed = parse_source(self.source, 'codex')
        self.assertFalse(parsed['errors'])
        self.assertEqual(parsed['turns'][0]['text'], '本人の発言\u2028続き\u2029終わり')

    def test_nontext_assets_are_registered_not_silently_completed(self):
        self.write_rows([{'type': 'message', 'role': 'user', 'content': [
            {'type': 'input_image', 'image_url': 'private'}, {'type': 'input_text', 'text': 'これ覚えて'}]}])
        parsed = parse_source(self.source, 'codex')
        self.assertEqual(parsed['assets'][0]['status'], 'unreviewed')

    def test_scan_resume_change_and_missing_source(self):
        self.write_rows([self.message('one')])
        ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions']))
        entry = ledger['sessions'][key]
        row = {'session': key, 'source_hash': entry['sha256'], 'chunk_id': entry['chunk_ids'][0],
               'outcome': 'no_durable_knowledge', 'reason': 'test'}
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        review(self.work, file, self.root)
        self.assertEqual(len(scan(self.root, self.work)['sessions'][key]['reviews']), 1)
        self.write_rows([self.message('one'), self.message('new decision')])
        self.assertFalse(scan(self.root, self.work)['sessions'][key]['reviews'])
        with self.assertRaises(ValueError):
            review(self.work, file, self.root)
        self.source.unlink()
        self.assertFalse(scan(self.root, self.work)['sessions'][key]['present'])

    def test_saved_outcome_requires_existing_note_and_pending_stays_open(self):
        self.write_rows([self.message('one')]); ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions'])); entry = ledger['sessions'][key]
        row = {'session': key, 'source_hash': entry['sha256'], 'chunk_id': entry['chunk_ids'][0],
               'outcome': 'recovered', 'reason': 'test', 'destinations': ['missing.md']}
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        with self.assertRaises(ValueError):
            review(self.work, file, self.root)
        row['outcome'] = 'needs_context'; file.write_text(json.dumps([row]))
        self.assertEqual(review(self.work, file, self.root)['reviewed_chunks'], 0)

    def test_source_changes_before_review_are_rejected(self):
        self.write_rows([self.message('one')]); ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions'])); entry = ledger['sessions'][key]
        row = {'session': key, 'source_hash': entry['sha256'], 'chunk_id': entry['chunk_ids'][0],
               'outcome': 'no_durable_knowledge', 'reason': 'test'}
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        self.write_rows([self.message('changed without rescan')])
        with self.assertRaises(ValueError):
            review(self.work, file, self.root)

    def test_batch_hashes_each_unchanged_source_once(self):
        self.write_rows([self.message('long text ' * 1200)])
        ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions'])); entry = ledger['sessions'][key]
        rows = [{'session': key, 'source_hash': entry['sha256'], 'chunk_id': chunk,
                 'outcome': 'no_durable_knowledge', 'reason': 'test'}
                for chunk in entry['chunk_ids']]
        self.assertGreater(len(rows), 1)
        file = self.root / 'review.json'; file.write_text(json.dumps(rows))
        with patch('recovery.digest', wraps=digest) as hashed:
            result = review(self.work, file, self.root)
        self.assertEqual(hashed.call_count, 1)
        self.assertEqual(result['reviewed_chunks'], len(rows))

    def test_change_during_batch_rejects_without_writing_ledger(self):
        self.write_rows([self.message('one')]); ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions'])); entry = ledger['sessions'][key]
        row = {'session': key, 'source_hash': entry['sha256'], 'chunk_id': entry['chunk_ids'][0],
               'outcome': 'already_saved', 'reason': 'test', 'destinations': ['note.md']}
        (self.root / 'note.md').write_text('saved')
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        before = (self.work / 'ledger.json').read_bytes()
        original_is_file = Path.is_file

        def mutate_when_checking_destination(path):
            if path == (self.root / 'note.md').resolve():
                self.source.write_text('changed after the source was hashed')
            return original_is_file(path)

        with patch.object(Path, 'is_file', mutate_when_checking_destination):
            with self.assertRaisesRegex(ValueError, 'changed during review'):
                review(self.work, file, self.root)
        self.assertEqual((self.work / 'ledger.json').read_bytes(), before)

    def test_external_original_requires_existing_unchanged_file(self):
        self.write_rows([self.message('save video')]); ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions'])); entry = ledger['sessions'][key]
        artifact = self.root / 'outside-video.mp4'; artifact.write_bytes(b'original')
        row = {'session': key, 'source_hash': entry['sha256'], 'chunk_id': entry['chunk_ids'][0],
               'outcome': 'already_saved', 'reason': 'original inspected', 'external_files': [
                   {'path': str(artifact), 'sha256': hashlib.sha256(b'original').hexdigest()}]}
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        self.assertEqual(review(self.work, file, self.root)['reviewed_chunks'], 1)
        artifact.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            review(self.work, file, self.root)
        artifact.unlink()
        with self.assertRaises(ValueError):
            review(self.work, file, self.root)

    def test_duplicate_annotation_does_not_skip_branch_text(self):
        self.write_rows([self.message('same'), self.message('shared')])
        second = self.source.with_name('b.jsonl')
        second.write_text(self.source.read_text() + '\n' + json.dumps(self.message('branch decision')))
        ledger = scan(self.root, self.work)
        branch = next(e for e in ledger['sessions'].values() if e['source'].endswith('b.jsonl'))
        self.assertEqual(branch['shared_prefix']['turn_count'], 2)
        self.assertFalse(branch['reviews'])

    def test_shortest_order_keeps_long_session_in_queue(self):
        self.write_rows([self.message('long text ' * 1200)])
        second = self.source.with_name('b.jsonl')
        second.write_text(json.dumps(self.message('short decision')))
        ledger = scan(self.root, self.work)
        short_key = next(k for k, e in ledger['sessions'].items() if e['source'].endswith('b.jsonl'))
        packet(self.work, 8000)
        items = json.loads((self.work / 'packet.json').read_text())['items']
        self.assertEqual(items[0]['session'], short_key)
        row = {'session': short_key, 'source_hash': items[0]['source_hash'],
               'chunk_id': items[0]['chunk']['id'], 'outcome': 'no_durable_knowledge', 'reason': 'test'}
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        review(self.work, file, self.root)
        packet(self.work, 8000)
        self.assertTrue(all(i['session'] != short_key for i in json.loads((self.work / 'packet.json').read_text())['items']))
        self.assertTrue(json.loads((self.work / 'packet.json').read_text())['items'])

    def test_pending_is_deferred_but_can_be_selected(self):
        self.write_rows([self.message('original needed')])
        ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions'])); entry = ledger['sessions'][key]
        row = {'session': key, 'source_hash': entry['sha256'], 'chunk_id': entry['chunk_ids'][0],
               'outcome': 'needs_context', 'reason': 'locate original'}
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        result = review(self.work, file, self.root)
        self.assertEqual(result['reviewed_chunks'], 0)
        self.assertEqual(packet(self.work, 8000)['items'], 0)
        self.assertEqual(packet(self.work, 8000, include_pending=True)['items'], 1)
        self.assertEqual(packet(self.work, 8000, session=key)['items'], 1)

    def test_matching_pending_survives_source_metadata_change(self):
        self.write_rows([self.message('original needed')])
        ledger = scan(self.root, self.work)
        key = next(iter(ledger['sessions'])); entry = ledger['sessions'][key]
        row = {'session': key, 'source_hash': entry['sha256'], 'chunk_id': entry['chunk_ids'][0],
               'outcome': 'needs_context', 'reason': 'locate original'}
        file = self.root / 'review.json'; file.write_text(json.dumps([row]))
        review(self.work, file, self.root)
        self.source.write_text(self.source.read_text() + '\n' + json.dumps({'type': 'ignored_metadata'}))
        updated = scan(self.root, self.work)['sessions'][key]
        self.assertEqual(updated['pending'][row['chunk_id']]['reason'], 'locate original')


if __name__ == '__main__':
    unittest.main()

"""Restart, scope, budget and invalidation checks using generated local fixtures."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit import material_memory as memory
from video_edit.common import EditError, read, write


class MaterialMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.job = Path(self.temp.name)
        self.rows = []
        for i in range(3):
            source = self.job / ('source%d.mp4' % i)
            source.write_bytes(b'synthetic source fixture')
            frame = self.job / ('frame%d.jpg' % i)
            frame.write_bytes(b'synthetic evidence declaration fixture')
            stat = source.stat()
            self.rows.append({'id': 'v%d' % i, 'filename': source.name, 'relative_path': source.name,
                'absolute_path': str(source), 'kind': 'video', 'duration': 10, 'status': 'analyzed',
                'fingerprint': {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns},
                'frames': [{'path': str(frame), 'time': 1}], 'contact_sheets': [str(frame)],
                'transcript': []})
        write(self.job / 'inventory.json', self.rows)
        write(self.job / 'request.json', {'theme': 'synthetic fixture only'})

    def make_result(self, packet):
        return {'schema_version': 'material-analysis-1.0', 'time_basis': 'source_seconds', 'assets': [
            {'id': a['id'], 'input_fingerprint': a['input_fingerprint'], 'status': 'reviewed',
             'coverage': {'contact_sheets_viewed': a['contact_sheets'], 'frame_times_viewed': [1]},
             'segments': [{'segment_id': a['id'] + '_s1', 'source_in': .5, 'source_out': 1.5,
                 'decision': 'candidate', 'observations': ['海边 synthetic declaration'],
                 'story_roles': ['establishing'], 'unknowns': ['Synthetic fixture, never actual review.'],
                 'evidence': [{'kind': 'frame', 'path': a['contact_sheets'][0], 'time': 1}]}]}
            for a in packet['assets']]}

    def finish(self, worker='worker'):
        claimed = memory.claim(self.job, worker)
        packet = memory.packet(self.job, claimed['batch_id'], worker)
        result = self.make_result(packet)
        path = self.job / 'result.json'
        write(path, result)
        memory.ingest(self.job, claimed['batch_id'], worker, path)
        return claimed, packet, path

    def test_scoped_claims_survive_restarts_and_do_not_overlap(self):
        memory.initialize(self.job, batch_size=2)
        a = memory.claim(self.job, 'a')
        b = memory.claim(self.job, 'b')
        self.assertNotEqual(a['batch_id'], b['batch_id'])
        pa = memory.packet(self.job, a['batch_id'], 'a')
        pb = memory.packet(self.job, b['batch_id'], 'b')
        self.assertFalse({x['id'] for x in pa['assets']} & {x['id'] for x in pb['assets']})
        self.assertEqual(memory.status(self.job)['batches']['running'], 2)
        self.assertFalse(memory.claim(self.job, 'c')['claimed'])

    def test_expired_lease_reclaimed_and_old_worker_cannot_commit(self):
        memory.initialize(self.job, batch_size=3)
        with patch.object(memory.time, 'time', return_value=1000):
            a = memory.claim(self.job, 'old', 1)
            packet = memory.packet(self.job, a['batch_id'], 'old')
        with patch.object(memory.time, 'time', return_value=1002):
            b = memory.claim(self.job, 'new', 20)
            self.assertEqual(a['batch_id'], b['batch_id'])
            path = self.job / 'old.json'; write(path, self.make_result(packet))
            with self.assertRaises(EditError) as caught:
                memory.ingest(self.job, a['batch_id'], 'old', path)
            self.assertEqual(caught.exception.code, 'MEMORY_LEASE')

    def test_ingest_search_compile_and_restart(self):
        memory.initialize(self.job, batch_size=2)
        self.finish()
        self.assertFalse(memory.compile_analysis(self.job)['status']['all_reviewed'])
        self.finish()
        self.assertTrue(memory.status(self.job)['all_reviewed'])
        found = memory.query(self.job, '海边', limit=2)
        self.assertEqual(len(found['candidates']), 2)
        self.assertTrue(found['more_available'])
        memory.initialize(self.job, batch_size=2)
        self.assertTrue(memory.status(self.job)['all_reviewed'])
        self.assertEqual(len(read(memory.compile_analysis(self.job)['analysis_path'])['assets']), 3)

    def test_scope_and_missing_evidence_are_rejected(self):
        memory.initialize(self.job, batch_size=3)
        claim = memory.claim(self.job, 'a')
        packet = memory.packet(self.job, claim['batch_id'], 'a')
        result = self.make_result(packet)
        path = self.job / 'result.json'
        for bad, code in ((dict(result, assets=result['assets'][:-1]), 'MEMORY_RESULT_SCOPE'),
                          (dict(result, assets=result['assets'] + [result['assets'][0]]), 'MEMORY_RESULT_SCOPE')):
            write(path, bad)
            with self.assertRaises(EditError) as caught:
                memory.ingest(self.job, claim['batch_id'], 'a', path)
            self.assertEqual(caught.exception.code, code)
        result['assets'][0]['segments'][0]['evidence'][0]['path'] = 'missing.jpg'
        write(path, result)
        with self.assertRaises(EditError): memory.ingest(self.job, claim['batch_id'], 'a', path)

    def test_input_change_invalidates_completed_batch(self):
        memory.initialize(self.job, batch_size=3)
        self.finish()
        rows = copy.deepcopy(self.rows)
        rows[0]['frames'][0]['time'] = 2
        write(self.job / 'inventory.json', rows)
        state = memory.initialize(self.job, batch_size=3)
        self.assertFalse(state['all_reviewed'])
        self.assertEqual(state['segment_count'], 0)
        self.assertEqual(state['assets']['pending'], 3)

    def test_source_changes_reject_stale_results(self):
        memory.initialize(self.job, batch_size=3)
        c = memory.claim(self.job, 'a')
        packet = memory.packet(self.job, c['batch_id'], 'a')
        Path(self.rows[0]['absolute_path']).write_bytes(b'changed source fixture, never user footage')
        path = self.job / 'result.json'; write(path, self.make_result(packet))
        with self.assertRaises(EditError) as caught:
            memory.ingest(self.job, c['batch_id'], 'a', path)
        self.assertEqual(caught.exception.code, 'MEMORY_STALE_SOURCE')

    def test_packet_budget_keeps_every_assignment_or_errors(self):
        for row in self.rows:
            row['transcript'] = [{'start': 0, 'end': 1, 'text': 'x' * 30000}]
        write(self.job / 'inventory.json', self.rows)
        memory.initialize(self.job, batch_size=3)
        c = memory.claim(self.job, 'a')
        packet = memory.packet(self.job, c['batch_id'], 'a', max_chars=5000)
        self.assertEqual(len(packet['assets']), 3)
        self.assertLessEqual(len(json.dumps(packet, ensure_ascii=False, separators=(',', ':'))), 5000)
        self.assertTrue(all(a['transcript_truncated'] for a in packet['assets']))
        with self.assertRaises(EditError): memory.packet(self.job, c['batch_id'], 'a', max_chars=1000)

    def test_large_inventory_bounded_packets_and_deleted_files(self):
        rows = [dict(self.rows[i % 3], id='v%03d' % i) for i in range(205)]
        write(self.job / 'inventory.json', rows)
        state = memory.initialize(self.job, batch_size=12)
        self.assertEqual(state['assets']['pending'], 205)
        self.assertEqual(state['batches']['pending'], 18)
        claim = memory.claim(self.job, 'a')
        packet = memory.packet(self.job, claim['batch_id'], 'a')
        self.assertLessEqual(len(packet['assets']), 12)
        write(self.job / 'inventory.json', rows[:-1])
        state = memory.initialize(self.job, batch_size=12)
        self.assertEqual(state['assets']['pending'], 204)

    def test_refinement_reopens_without_reanalysis_and_archives_old_evidence(self):
        memory.initialize(self.job, batch_size=3)
        claimed, _, _ = self.finish()
        previous = read(self.job / ('memory/results/' + claimed['batch_id'] + '.json'))
        memory.reopen(self.job, claimed['batch_id'])
        self.assertEqual(memory.query(self.job, '海边')['candidates'], [])
        c = memory.claim(self.job, 'refiner')
        packet = memory.packet(self.job, c['batch_id'], 'refiner')
        self.assertTrue(Path(packet['previous_result_path']).is_file())
        self.assertNotEqual(packet['result_path'], packet['previous_result_path'])
        with self.assertRaises(EditError): memory.reopen(self.job, c['batch_id'])
        result = self.make_result(packet)
        result['assets'][0]['segments'][0]['reason'] = 'Additional reviewed selection.'
        path = self.job / 'refined.json'; write(path, result)
        memory.ingest(self.job, c['batch_id'], 'refiner', path)
        archives = list((self.job / 'memory/history' / c['batch_id']).glob('*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(read(archives[0]), previous)
        self.assertTrue(memory.status(self.job)['all_reviewed'])

    def test_dense_evidence_search_returns_navigation_within_small_budget(self):
        memory.initialize(self.job, batch_size=3)
        c = memory.claim(self.job, 'a')
        packet = memory.packet(self.job, c['batch_id'], 'a')
        result = self.make_result(packet)
        for asset in result['assets']:
            asset['segments'][0]['evidence'] *= 200
        path = Path(packet['result_path']); write(path, result)
        memory.ingest(self.job, c['batch_id'], 'a', path)
        found = memory.query(self.job, '海边', limit=3, max_chars=2000)
        self.assertTrue(found['candidates'])
        candidate = found['candidates'][0]
        self.assertNotIn('evidence', candidate['segment'])
        self.assertEqual(len(read(candidate['detail_path'])['segment']['evidence']), 200)
        self.assertLessEqual(len(json.dumps(found, ensure_ascii=False, separators=(',', ':'))), 2000)


if __name__ == '__main__': unittest.main()

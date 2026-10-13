"""Source-bound evidence and exact mandatory-range regression fixtures.

Fixture files deliberately contain no real media or listening claim. File/time
validation is structural, never a substitute for an actual viewing tool event.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit.common import write
from video_edit.plan import validate
from video_edit.review_evidence import validate_analysis


class ReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'video.mp4'; self.source.write_bytes(b'synthetic range-validation fixture')
        self.frame = self.root/'frame.jpg'; self.frame.write_bytes(b'synthetic evidence-path fixture')
        self.row = {'id': 'v1', 'absolute_path': str(self.source), 'kind': 'video', 'duration': 10,
                    'width': 640, 'height': 360, 'fps': 30, 'has_audio': False,
                    'frames': [{'path': str(self.frame), 'time': 2}]}
        self.plan = {'schema_version': '1.0', 'width': 640, 'height': 360, 'fps': 30, 'duration': 2,
                    'inventory': [self.row], 'request': {'voiceover': False},
                    'shots': [{'id': 'v1', 'index': 1, 'source_in': 2, 'duration': 2, 'speed': 1, 'start': 0}],
                    'review': {'status': 'reviewed', 'evidence': [self.evidence()]}}
        self.analysis = {'schema_version': 'material-analysis-1.0', 'time_basis': 'source_seconds',
            'assets': [{'id': 'v1', 'status': 'reviewed', 'coverage': {
                'frame_times_viewed': [2], 'playback_ranges': [{'source_start': 1, 'source_end': 5}]},
                'segments': [{'segment_id': 'v1_s1', 'source_in': 1, 'source_out': 5,
                              'decision': 'candidate', 'evidence': [self.evidence()]}]}]}

    def evidence(self, **kwargs):
        return {'asset_id': 'v1', 'path': str(self.frame), 'time': 2, **kwargs}

    def result(self):
        return validate(self.plan, self.root/'plan.json', {}, inspect_files=False)

    def codes(self):
        return {e['code'] for e in self.result()['errors']}

    def strict(self):
        write(self.root/'material-analysis.json', self.analysis)
        self.plan['review']['analysis_path'] = 'material-analysis.json'
        self.plan['shots'][0]['segment_id'] = 'v1_s1'

    def test_real_file_time_declaration_is_structurally_valid(self):
        self.assertTrue(self.result()['valid'], self.result())

    def test_missing_structured_file_and_invalid_source_time_fail(self):
        self.plan['review']['evidence'] = [self.evidence(path='missing.jpg', time=11)]
        self.assertTrue({'REVIEW_EVIDENCE_MISSING', 'REVIEW_EVIDENCE_TIME'} <= self.codes())

    def test_missing_legacy_path_fails_but_prose_warns(self):
        self.plan['review']['evidence'] = ['frames/nonexistent.jpg']
        self.assertIn('REVIEW_EVIDENCE_MISSING', self.codes())
        self.plan['review']['evidence'] = ['Synthetic handwritten fixture summary only']
        result = self.result()
        self.assertTrue(result['valid'], result)
        self.assertTrue(any('LEGACY_REVIEW_EVIDENCE' in w for w in result['warnings']))
        self.plan['review']['evidence'] = 'Synthetic generated color fixtures, known pixel and tone expectations.'
        self.assertTrue(self.result()['valid'], self.result())

    def test_structured_interval_and_wrong_asset_validation(self):
        self.plan['review']['evidence'] = [{'asset_id': 'v1', 'path': str(self.source),
                                         'source_start': 2, 'source_end': 4, 'kind': 'playback'}]
        self.assertTrue(self.result()['valid'], self.result())
        self.plan['review']['evidence'][0]['asset_id'] = 'missing'
        self.assertIn('REVIEW_EVIDENCE_ASSET', self.codes())

    def test_must_keep_means_complete_source_range_not_file_presence(self):
        self.plan['request']['must_keep_ranges'] = [{'asset_id': 'v1', 'source_start': 3, 'source_end': 5}]
        self.assertIn('MUST_KEEP_RANGE_MISSING', self.codes())
        self.plan['request']['must_keep_ranges'][0].update(source_start=2, source_end=4)
        self.assertTrue(self.result()['valid'], self.result())

    def test_must_keep_union_accounts_for_speed_and_gaps(self):
        self.plan.update(duration=2)
        self.plan['shots'] = [dict(self.plan['shots'][0], duration=1, speed=2),
                              dict(self.plan['shots'][0], index=2, start=1, source_in=4, duration=1, speed=2)]
        self.plan['request']['must_keep_ranges'] = [{'asset_id': 'v1', 'source_start': 2, 'source_end': 6}]
        self.assertTrue(self.result()['valid'], self.result())
        self.plan['shots'][1]['source_in'] = 4.5
        self.assertIn('MUST_KEEP_RANGE_MISSING', self.codes())

    def test_strict_sidecar_segment_and_playback_coverage(self):
        self.strict()
        self.assertTrue(self.result()['valid'], self.result())
        self.plan['shots'][0]['segment_id'] = 'v1_does_not_exist'
        self.assertIn('ANALYSIS_SEGMENT_REF', self.codes())

    def test_strict_source_range_and_unreviewed_asset_fail(self):
        self.analysis['assets'][0]['segments'][0]['source_out'] = 3
        self.strict()
        self.assertIn('ANALYSIS_SEGMENT_RANGE', self.codes())
        self.analysis['assets'][0]['status'] = 'pending'; self.strict()
        self.assertIn('SELECTED_NOT_REVIEWED', self.codes())

    def test_sparse_frames_do_not_claim_selected_coverage(self):
        self.analysis['assets'][0]['coverage']['playback_ranges'] = []
        self.strict()
        self.assertIn('ANALYSIS_SELECTION_COVERAGE', self.codes())

    def test_dense_frame_coverage_warns_about_continuous_qa(self):
        asset = self.analysis['assets'][0]
        asset['coverage'].update(playback_ranges=[], frame_times_viewed=[2, 2.5, 3, 3.5, 4])
        asset['segments'][0]['evidence'] = [self.evidence(time=t) for t in [2, 2.5, 3, 3.5, 4]]
        self.strict()
        result = self.result()
        self.assertTrue(result['valid'], result)
        self.assertTrue(any('密集抽帧' in w for w in result['warnings']))

    def test_mismatched_fingerprint_or_missing_frame_provenance_fails(self):
        self.analysis['assets'][0]['fingerprint'] = {'size': 0}
        self.analysis['assets'][0]['coverage']['frame_times_viewed'] = [7]
        self.strict()
        self.assertTrue({'ANALYSIS_SOURCE_CHANGED', 'ANALYSIS_COVERAGE_EVIDENCE'} <= self.codes())

    def test_strict_link_requires_current_fingerprint_when_available(self):
        self.row['fingerprint'] = {'size': self.source.stat().st_size,
                                   'mtime_ns': self.source.stat().st_mtime_ns}
        self.strict()
        self.assertIn('ANALYSIS_FINGERPRINT_REQUIRED', self.codes())
        self.analysis['assets'][0]['fingerprint'] = deepcopy(self.row['fingerprint'])
        self.strict()
        self.assertTrue(self.result()['valid'], self.result())

    def test_generated_image_zero_duration_has_static_review_extent(self):
        self.row.update(kind='image', duration=0)
        self.plan['shots'][0].update(source_in=0, duration=2)
        self.analysis['assets'][0]['segments'][0].update(source_in=0, source_out=5,
                                                       evidence=[self.evidence(time=0)])
        self.analysis['assets'][0]['coverage'].update(playback_ranges=[], frame_times_viewed=[0])
        self.plan['review']['evidence'] = [self.evidence(time=0)]
        self.strict()
        self.assertTrue(self.result()['valid'], self.result())

    def test_public_analysis_validator_accepts_batch_subset(self):
        rows = [self.row, dict(self.row, id='v2')]
        self.assertEqual(validate_analysis(self.analysis, rows, self.root), [])
        self.assertEqual(validate_analysis(self.analysis, [self.row], self.root), [])

    def test_strict_link_checks_layer_segment_ids(self):
        self.strict()
        self.plan['visual_layers'] = [{'id': 'v1', 'source_in': 2, 'start': 0, 'duration': 2,
                                      'segment_id': 'v1_s1'}]
        self.assertTrue(self.result()['valid'], self.result())
        self.plan['visual_layers'][0]['segment_id'] = 'missing'
        self.assertIn('ANALYSIS_SEGMENT_REF', self.codes())

    def test_malformed_evidence_is_reported_without_exception(self):
        for value in (None, False, {}, [False], [{'asset_id': 'v1', 'path': None, 'time': True}]):
            self.plan['review']['evidence'] = value
            self.assertFalse(self.result()['valid'])


if __name__ == '__main__': unittest.main()

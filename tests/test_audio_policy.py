"""Original-sound policy checks; no media, FFmpeg or Jianying required.

Run from the skill directory: python -m unittest discover -s tests -v
Review declarations below are synthetic fixtures, never real listening claims.
"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.audio_policy import denoise_filter, original_audio_window, validate_original_audio
from video_edit.common import EditError


class OriginalAudioPolicyTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{'id': 'clip', 'kind': 'video', 'duration': 5, 'has_audio': True}]
        self.plan = {
            'duration': 3,
            'shots': [{'index': 1, 'id': 'clip', 'start': .5, 'duration': 1,
                       'source_in': 1, 'speed': 1, 'audio_gain': .6,
                       'audio_lead': .2, 'audio_tail': .3,
                       'audio_review': {
                           'status': 'approved', 'purpose': 'key_speech',
                           'source_start': .8, 'source_end': 2.3, 'quality': 'clear',
                           'evidence': 'Synthetic test declaration; no actual listening claim.',
                           'reason': 'Synthetic story-value declaration for policy testing.'}}]}

    def codes(self, plan=None, rows=None):
        errors = []
        validate_original_audio(self.plan if plan is None else plan,
                                self.rows if rows is None else rows,
                                lambda code, where, message: errors.append(code))
        return errors

    def test_missing_or_zero_gain_requires_no_approval(self):
        for gain in (None, 0):
            with self.subTest(gain=gain):
                p = copy.deepcopy(self.plan)
                shot = p['shots'][0]
                shot.pop('audio_review')
                if gain is None:
                    shot.pop('audio_gain')
                else:
                    shot['audio_gain'] = gain
                self.assertEqual(self.codes(p), [])

    def test_positive_legacy_gain_needs_fresh_review(self):
        self.plan['shots'][0].pop('audio_review')
        self.assertIn('ORIGINAL_AUDIO_REVIEW_REQUIRED', self.codes())

    def test_only_normal_speed_can_keep_sound(self):
        for speed in (.25, .5, 2, 4):
            with self.subTest(speed=speed):
                self.plan['shots'][0]['speed'] = speed
                self.assertIn('ORIGINAL_AUDIO_SPEED', self.codes())
                muted = copy.deepcopy(self.plan)
                muted['shots'][0]['audio_gain'] = 0
                self.assertEqual(self.codes(muted), [])

    def test_clear_story_sound_and_key_speech_are_allowed(self):
        for purpose in ('key_speech', 'story_sound'):
            with self.subTest(purpose=purpose):
                self.plan['shots'][0]['audio_review']['purpose'] = purpose
                self.assertEqual(self.codes(), [])

    def test_noise_unknown_quality_and_pending_review_are_rejected(self):
        for field, value, code in (
                ('quality', 'noisy', 'ORIGINAL_AUDIO_QUALITY'),
                ('quality', 'unknown', 'ORIGINAL_AUDIO_QUALITY'),
                ('status', 'pending', 'ORIGINAL_AUDIO_REVIEW_REQUIRED'),
                ('purpose', 'background', 'ORIGINAL_AUDIO_PURPOSE')):
            with self.subTest(field=field, value=value):
                p = copy.deepcopy(self.plan)
                p['shots'][0]['audio_review'][field] = value
                self.assertIn(code, self.codes(p))

    def test_listening_evidence_and_story_reason_are_required(self):
        for field in ('evidence', 'reason'):
            with self.subTest(field=field):
                p = copy.deepcopy(self.plan)
                p['shots'][0]['audio_review'][field] = '  '
                self.assertIn('ORIGINAL_AUDIO_REVIEW', self.codes(p))

    def test_review_must_cover_j_l_extensions(self):
        for field, value in (('source_start', 1), ('source_end', 2),
                             ('source_start', -1), ('source_end', 6),
                             ('source_end', float('nan'))):
            with self.subTest(field=field, value=value):
                p = copy.deepcopy(self.plan)
                p['shots'][0]['audio_review'][field] = value
                self.assertIn('ORIGINAL_AUDIO_REVIEW_RANGE', self.codes(p))

    def test_j_l_extensions_respect_source_and_timeline_boundaries(self):
        shot = dict(self.plan['shots'][0], start=.1, source_in=.05,
                    audio_lead=4, audio_tail=4)
        window = original_audio_window(shot, total=1.3, source_duration=5)
        self.assertAlmostEqual(window['source_start'], 0)
        self.assertAlmostEqual(window['start'], .05)
        self.assertAlmostEqual(window['source_end'], 1.25)
        self.assertAlmostEqual(window['duration'], 1.25)
        window = original_audio_window(shot, total=8, source_duration=1.2)
        self.assertAlmostEqual(window['source_end'], 1.2)

    def test_invalid_gain_and_missing_audio_are_rejected(self):
        for gain in (True, -1, 3, float('inf')):
            with self.subTest(gain=gain):
                p = copy.deepcopy(self.plan)
                p['shots'][0]['audio_gain'] = gain
                self.assertIn('ORIGINAL_AUDIO_GAIN', self.codes(p))
        self.assertIn('ORIGINAL_AUDIO_SOURCE', self.codes(rows=[]))
        self.assertIn('ORIGINAL_AUDIO_SOURCE', self.codes(rows=[dict(self.rows[0], has_audio=False)]))
        self.assertIn('ORIGINAL_AUDIO_SOURCE', self.codes(rows=[dict(self.rows[0], kind='image')]))

    def test_split_screen_cannot_claim_to_keep_original_audio(self):
        panel = copy.deepcopy(self.plan['shots'][0])
        p = {'duration': 3, 'shots': [], 'panels': [panel]}
        self.assertIn('ORIGINAL_AUDIO_PANEL', self.codes(p))
        self.plan['shots'][0]['purpose'] = 'panels_triptych'
        self.assertIn('ORIGINAL_AUDIO_PANEL', self.codes())

    def test_denoise_requires_processed_sample_listening_evidence(self):
        review = self.plan['shots'][0]['audio_review']
        review['denoise'] = {'filter': 'afftdn', 'noise_reduction': 8}
        self.assertIn('ORIGINAL_AUDIO_DENOISE_REVIEW', self.codes())
        review['denoise']['evidence'] = 'Synthetic processed-sample review declaration.'
        self.assertEqual(self.codes(), [])

    def test_denoise_allows_only_fixed_mild_filter_parameters(self):
        self.assertIsNone(denoise_filter(None))
        self.assertEqual(denoise_filter({'filter': 'afftdn'}), 'afftdn=nr=8')
        for settings in (
                {'filter': 'volume', 'noise_reduction': 8},
                {'filter': 'afftdn', 'noise_reduction': 40},
                {'filter': 'afftdn', 'noise_reduction': True},
                {'filter': 'afftdn', 'noise_reduction': float('nan')},
                {'filter': 'afftdn', 'raw_filter': 'unsupported'}):
            with self.subTest(settings=settings), self.assertRaises(EditError) as context:
                denoise_filter(settings)
            self.assertEqual(context.exception.code, 'ORIGINAL_AUDIO_DENOISE')


if __name__ == '__main__':
    unittest.main()

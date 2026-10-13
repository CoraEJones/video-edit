"""Measured loudness is a technical report, never a synthetic listening pass."""
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit import sound
from video_edit.common import EditError, read, run, sha256


class SoundQcTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'tone.wav'
        t = np.arange(sound.SR*2)/sound.SR
        mono = .1*np.sin(2*math.pi*1000*t)
        sound.wavwrite(self.source, np.column_stack([mono, mono]))
        self.cfg = {'ffmpeg': os.environ.get('VIDEO_EDIT_FFMPEG')}

    def test_missing_tool_and_file_are_explicit_nonpassing_states(self):
        result = sound.measure_loudness(self.source, {})
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['integrated_lufs'])
        self.assertFalse(result['listening_review_completed'])
        self.assertEqual(sound.measure_loudness(self.root/'missing.wav', {})['status'], 'file_missing')
        result = sound.measure_loudness(self.source, {'ffmpeg': str(self.root/'missing-ffmpeg.exe')})
        self.assertEqual(result['status'], 'unavailable')

    def test_filter_failure_is_recorded_without_claiming_success(self):
        with patch.object(sound, 'run', side_effect=EditError('PROCESS_FAILED', 'filter failed',
                                      {'stderr': "No such filter: 'loudnorm'"})):
            result = sound.measure_loudness(self.source, {'ffmpeg': 'synthetic-configured-tool'})
        self.assertEqual(result['status'], 'unsupported')
        self.assertIsNone(result['true_peak_dbtp'])

    def test_invalid_measurement_json_is_failed(self):
        from types import SimpleNamespace
        for stderr in (b'No JSON returned', b'{"input_i": "-20", "input_tp": "bad", "input_lra": "0"}'):
            with patch.object(sound, 'run', return_value=SimpleNamespace(stderr=stderr)):
                result = sound.measure_loudness(self.source, {'ffmpeg': 'synthetic-tool'})
            self.assertEqual(result['status'], 'failed')

    def test_report_preserves_failed_status_and_has_no_delivery_target(self):
        report = sound.write_audio_qc(self.root, {}, mix_wav=self.source)
        self.assertEqual(report['measurements']['mix_wav']['status'], 'unavailable')
        self.assertTrue(report['warnings'])
        self.assertIsNone(report['delivery_target'])
        self.assertFalse(report['normalization_applied_by_measurement'])
        self.assertFalse(report['listening_review_completed'])
        self.assertEqual(read(self.root/'audio-qc.json'), report)
        report = sound.write_audio_qc(self.root, {}, declared_target={'integrated_lufs': -18}, final_encoded=self.source)
        self.assertEqual(report['delivery_target'], {'integrated_lufs': -18})
        self.assertEqual(report['target_assessment'], 'reported_only_target_not_automatically_assessed')

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set VIDEO_EDIT_FFMPEG for actual loudness measurement')
    def test_real_tone_loudness_true_peak_and_no_file_modification(self):
        before = sha256(self.source)
        measured = sound.measure_loudness(self.source, self.cfg)
        self.assertEqual(measured['status'], 'measured', measured)
        self.assertAlmostEqual(measured['true_peak_dbtp'], -20, delta=.2)
        self.assertTrue(-25 < measured['integrated_lufs'] < -15, measured)
        self.assertEqual(measured['lra_lu'], 0)
        self.assertEqual(sha256(self.source), before)
        self.assertFalse(measured['normalization_applied'])
        self.assertFalse(measured['listening_review_completed'])

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set VIDEO_EDIT_FFMPEG for actual silent measurement')
    def test_real_silence_is_not_reported_as_finite_loudness(self):
        import numpy as np
        silent = self.root/'silence.wav'
        sound.wavwrite(silent, np.zeros((sound.SR*2, 2)))
        measured = sound.measure_loudness(silent, self.cfg)
        self.assertEqual(measured['status'], 'silent', measured)
        self.assertIsNone(measured['integrated_lufs'])
        self.assertIsNone(measured['true_peak_dbtp'])
        # Strict JSON serialization must not emit NaN/Infinity.
        report = sound.write_audio_qc(self.root, self.cfg, mix_wav=silent)
        self.assertEqual(report['warnings'], [])
        self.assertNotIn('Infinity', (self.root/'audio-qc.json').read_text())

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set VIDEO_EDIT_FFMPEG for actual AAC measurement')
    def test_real_encoded_aac_is_measured_independently_and_report_is_merged(self):
        encoded = self.root/'encoded.m4a'
        run([self.cfg['ffmpeg'], '-v', 'error', '-i', self.source, '-c:a', 'aac', '-b:a', '128k', '-y', encoded])
        sound.write_audio_qc(self.root, self.cfg, mix_wav=self.source)
        report = sound.write_audio_qc(self.root, self.cfg, final_encoded=encoded)
        self.assertEqual(set(report['measurements']), {'mix_wav', 'final_encoded'})
        final = report['measurements']['final_encoded']
        self.assertEqual(final['status'], 'measured', final)
        self.assertAlmostEqual(final['integrated_lufs'], report['measurements']['mix_wav']['integrated_lufs'], delta=.5)
        self.assertEqual(Path(final['path']).resolve(), encoded.resolve())

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set VIDEO_EDIT_FFMPEG for actual no-audio detection')
    def test_real_file_without_audio_is_explicit(self):
        movie = self.root/'silent-video.mp4'
        run([self.cfg['ffmpeg'], '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=32x32:r=25:d=0.2',
             '-c:v', 'libx264', '-an', '-y', movie])
        measured = sound.measure_loudness(movie, self.cfg)
        self.assertEqual(measured['status'], 'no_audio', measured)


if __name__ == '__main__': unittest.main()

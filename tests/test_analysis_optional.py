"""Real tiny-photo analysis and synthetic audio-video boundary tests.

The synthetic video probe/frame extractor is deliberate: these tests exercise
optional speech failures, not FFmpeg's decoder or recognition model accuracy.
"""
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit import analysis
from video_edit.common import EditError, read
from video_edit.intake import DEFAULTS, confirm_request


class OptionalAnalysisTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        import numpy  # Load outside sys.modules fixtures so cleanup never reloads it.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.media = self.root/'media'; self.media.mkdir()
        self.out = self.root/'analysis'
        self.cfg = {'font_path': str(self.root/'missing-default-font.ttf'),
                    'ffmpeg': 'not-called-for-photo', 'max_samples_per_video': 3,
                    'sample_interval_seconds': 8, 'transcription_required': False}
        Image.new('RGB', (24, 16), '#23767d').save(self.media/'photo.png')

    def request(self):
        # Explicit confirmations here are test fixtures, never real user consent.
        return confirm_request(dict(DEFAULTS, media_dir=str(self.media),
                                    output_dir=str(self.root/'delivery')), True)

    def synthetic_video(self):
        (self.media/'photo.png').unlink()
        (self.media/'synthetic.mp4').write_bytes(b'synthetic fixture for mocked probe')
        def extract(command, **kwargs):
            from PIL import Image
            target = Path(command[-1])
            if target.suffix == '.jpg': Image.new('RGB', (24, 16), '#23767d').save(target)
            else: target.write_bytes(b'synthetic audio fixture')
        for mocked in (patch.object(analysis, 'probe', return_value={'duration': 1, 'fps': 25,
                        'width': 24, 'height': 16, 'has_audio': True}),
                       patch.object(analysis, 'run', side_effect=extract)):
            mocked.start(); self.addCleanup(mocked.stop)

    def test_real_photo_without_model_has_visual_evidence(self):
        with patch.object(analysis, 'model_path', return_value=None):
            result = analysis.analyze(self.media, self.out, self.request(), self.cfg)
        self.assertEqual(result['ready_count'], 1)
        row = read(result['inventory'])[0]
        self.assertEqual(row['status'], 'analyzed')
        self.assertEqual(row['transcription_status'], 'no_audio')
        self.assertTrue(Path(row['frames'][0]['path']).is_file())
        self.assertTrue(Path(row['contact_sheets'][0]).is_file())

    def test_model_present_but_missing_library_keeps_visual_results(self):
        self.synthetic_video()
        with patch.object(analysis, 'model_path', return_value='synthetic-model'), \
             patch.dict(sys.modules, {'faster_whisper': None}):
            result = analysis.analyze(self.media, self.out, self.request(), self.cfg)
        row = read(result['inventory'])[0]
        self.assertEqual(result['ready_count'], 1)
        self.assertEqual(row['status'], 'analyzed')
        self.assertEqual(row['transcription_status'], 'failed')
        self.assertEqual(row['transcript'], [])
        self.assertEqual(len(row['frames']), 3)
        self.assertIn('faster_whisper', row['transcription_error'])

    def test_recognition_failure_keeps_visual_results(self):
        self.synthetic_video()
        class BrokenRecognizer:
            def __init__(self, *args, **kwargs): pass
            def transcribe(self, *args, **kwargs): raise RuntimeError('synthetic ASR failure')
        with patch.object(analysis, 'model_path', return_value='synthetic-model'), \
             patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=BrokenRecognizer)}):
            result = analysis.analyze(self.media, self.out, self.request(), self.cfg)
        self.assertEqual(result['ready_count'], 1)
        self.assertEqual(read(result['inventory'])[0]['transcription_status'], 'failed')
        self.assertTrue(any('synthetic ASR failure' in message for message in result['warnings']))

    def test_required_transcription_missing_model_blocks(self):
        with patch.object(analysis, 'model_path', return_value=None):
            with self.assertRaises(EditError) as caught:
                analysis.analyze(self.media, self.out, self.request(), dict(self.cfg, transcription_required=True))
        self.assertEqual(caught.exception.code, 'TRANSCRIPTION_UNAVAILABLE')
        self.assertFalse((self.out/'analysis-report.json').exists())

    def test_required_transcription_library_failure_blocks(self):
        self.synthetic_video()
        with patch.object(analysis, 'model_path', return_value='synthetic-model'), \
             patch.dict(sys.modules, {'faster_whisper': None}):
            with self.assertRaises(EditError) as caught:
                analysis.analyze(self.media, self.out, self.request(), dict(self.cfg, transcription_required=True))
        self.assertEqual(caught.exception.code, 'TRANSCRIPTION_FAILED')
        self.assertFalse((self.out/'analysis-report.json').exists())

    def test_required_transcription_cannot_be_silently_disabled(self):
        with self.assertRaises(EditError) as caught:
            analysis.analyze(self.media, self.out, self.request(), dict(self.cfg, transcription_required=True), transcribe=False)
        self.assertEqual(caught.exception.code, 'TRANSCRIPTION_REQUIRED')

    def test_ogv_video_is_discovered_for_public_theora_sources(self):
        self.synthetic_video()
        (self.media/'synthetic.mp4').rename(self.media/'synthetic.ogv')
        with patch.object(analysis, 'model_path', return_value=None):
            result = analysis.analyze(self.media, self.out, self.request(), self.cfg, transcribe=False)
        self.assertEqual(result['ready_count'], 1)
        self.assertEqual(read(result['inventory'])[0]['filename'], 'synthetic.ogv')


if __name__ == '__main__': unittest.main()

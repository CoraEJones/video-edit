"""Regression coverage for mixed hits, configuration changes and ASR recovery."""
from pathlib import Path
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit import analysis
from video_edit.common import EditError, read
from video_edit.intake import DEFAULTS, confirm_request


class AnalysisCacheTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image
        import numpy
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.media = self.root/'media'; self.media.mkdir()
        self.out = self.root/'analysis'
        self.cfg = {'font_path': str(self.root/'no-font'), 'ffmpeg': 'mock-ffmpeg',
                    'max_samples_per_video': 30, 'sample_interval_seconds': 8,
                    'transcription_required': False}
        self.image = Image

    def request(self):
        return confirm_request(dict(DEFAULTS, media_dir=str(self.media),
                                    output_dir=str(self.root/'delivery')), True)

    def photo(self, name, color='#123456'):
        path = self.media/name; self.image.new('RGB', (32, 20), color).save(path); return path

    def analyze(self, cfg=None, **kwargs):
        with patch.object(analysis, 'model_path', return_value=None):
            return analysis.analyze(self.media, self.out, self.request(), cfg or self.cfg, **kwargs)

    def video(self, has_audio=False, duration=32):
        path = self.media/'video.mp4'; path.write_bytes(b'synthetic mocked decoder fixture')
        def extract(command, **kwargs):
            target = Path(command[-1])
            if target.suffix == '.jpg': self.image.new('RGB', (32, 20), '#543210').save(target)
            else: target.write_bytes(b'synthetic PCM fixture')
        decoder = patch.object(analysis, 'run', side_effect=extract).start()
        self.addCleanup(patch.stopall)
        probe = patch.object(analysis, 'probe', return_value={'duration': duration, 'width': 32,
                  'height': 20, 'fps': 25, 'has_audio': has_audio}).start()
        return decoder, probe

    def test_miss_then_hit_retains_full_inventory_and_checkpoint(self):
        self.photo('a.png'); self.photo('b.png')
        self.analyze()
        self.photo('a.png', '#abcdef')
        writes = []
        real_write = analysis.write
        def checkpoint(path, value):
            if Path(path).name == 'inventory.json': writes.append([r['filename'] for r in value])
            real_write(path, value)
        with patch.object(analysis, 'write', side_effect=checkpoint):
            result = self.analyze()
        self.assertEqual([r['filename'] for r in read(result['inventory'])], ['a.png', 'b.png'])
        self.assertEqual(result['cache']['visual'], {'hits': 1, 'runs': 1})
        self.assertIn(['a.png'], writes)
        self.assertEqual(writes[-1], ['a.png', 'b.png'])

    def test_deletion_and_all_hits_refresh_list(self):
        first = self.photo('a.png'); self.photo('b.png'); self.analyze()
        first.unlink(); result = self.analyze()
        self.assertEqual([r['filename'] for r in read(result['inventory'])], ['b.png'])
        self.assertEqual(result['cache']['visual']['hits'], 1)
        request = self.request()
        (self.media/'b.png').unlink()
        # The public intake guard correctly refuses an empty source folder;
        # exercise the internal rescan path with a previously valid request.
        with patch('video_edit.intake.require_confirmed_request'):
            with self.assertRaises(EditError) as caught:
                analysis.analyze(self.media, self.out, request, self.cfg)
        self.assertEqual(caught.exception.code, 'NO_MEDIA')
        self.assertEqual(read(self.out/'inventory.json'), [])

    def test_no_audio_video_is_cache_hit_without_reprobe_or_decode(self):
        decoder, probe = self.video()
        self.analyze(); decoder.reset_mock(); probe.reset_mock()
        result = self.analyze()
        decoder.assert_not_called(); probe.assert_not_called()
        self.assertEqual(result['cache']['transcription']['hits'], 1)
        self.assertEqual(read(result['inventory'])[0]['transcription_status'], 'no_audio')

    def test_sampling_configuration_invalidates_visual_only(self):
        decoder, probe = self.video()
        first = self.analyze(); old_times = [f['time'] for f in read(first['inventory'])[0]['frames']]
        decoder.reset_mock(); probe.reset_mock()
        result = self.analyze(dict(self.cfg, sample_interval_seconds=2))
        self.assertEqual(result['cache']['visual']['runs'], 1)
        self.assertEqual(result['cache']['transcription']['hits'], 1)
        self.assertNotEqual(old_times, [f['time'] for f in read(result['inventory'])[0]['frames']])
        probe.assert_not_called()

    def test_missing_contact_sheet_regenerates_visual_evidence(self):
        self.photo('a.png'); result = self.analyze()
        Path(read(result['inventory'])[0]['contact_sheets'][0]).unlink()
        self.assertEqual(self.analyze()['cache']['visual']['runs'], 1)

    def test_language_change_runs_asr_without_resampling(self):
        decoder, probe = self.video(has_audio=True)
        calls = []
        class Recognizer:
            def __init__(self, *args, **kwargs): pass
            def transcribe(self, path, **kwargs):
                calls.append(kwargs['language'])
                return iter([]), types.SimpleNamespace(language='en', language_probability=.99)
        module = types.SimpleNamespace(WhisperModel=Recognizer)
        with patch.object(analysis, 'model_path', return_value='mock-model'), patch.dict(sys.modules, {'faster_whisper': module}):
            analysis.analyze(self.media, self.out, self.request(), dict(self.cfg, input_language='en'))
            decoder.reset_mock(); probe.reset_mock()
            result = analysis.analyze(self.media, self.out, self.request(), dict(self.cfg, input_language='zh'))
        self.assertEqual(calls, ['en', 'zh'])
        self.assertEqual(result['cache']['visual']['hits'], 1)
        self.assertEqual(len(decoder.call_args_list), 1)
        self.assertEqual(Path(decoder.call_args.args[0][-1]).suffix, '.wav')
        probe.assert_not_called()

    def test_failed_asr_retries_and_required_failure_preserves_frames(self):
        decoder, _ = self.video(has_audio=True)
        class Broken:
            def __init__(self, *args, **kwargs): pass
            def transcribe(self, *args, **kwargs): raise RuntimeError('synthetic retryable error')
        module = types.SimpleNamespace(WhisperModel=Broken)
        with patch.object(analysis, 'model_path', return_value='mock-model'), patch.dict(sys.modules, {'faster_whisper': module}):
            with self.assertRaises(EditError):
                analysis.analyze(self.media, self.out, self.request(), dict(self.cfg, transcription_required=True))
            row = read(self.out/'inventory.json')[0]
            self.assertEqual(row['status'], 'analyzed')
            self.assertEqual(row['transcription_status'], 'failed')
            self.assertTrue(row['frames'])
            decoder.reset_mock()
            result = analysis.analyze(self.media, self.out, self.request(), self.cfg)
        self.assertEqual(result['cache']['visual']['hits'], 1)
        self.assertEqual(result['cache']['transcription']['runs'], 1)
        self.assertEqual(len(decoder.call_args_list), 1)

    def test_source_change_invalidates_all_stages(self):
        decoder, _ = self.video()
        self.analyze(); (self.media/'video.mp4').write_bytes(b'changed synthetic fixture with different bytes')
        result = self.analyze()
        self.assertTrue(all(v['runs'] == 1 for v in result['cache'].values()))

    def test_failed_decoder_rows_remain_in_list_and_retry(self):
        (self.media/'broken.mp4').write_bytes(b'synthetic broken video')
        with patch.object(analysis, 'probe', side_effect=RuntimeError('synthetic probe failure')):
            result = self.analyze()
        row = read(result['inventory'])[0]
        self.assertEqual(row['status'], 'analysis_failed')
        self.assertEqual(row['duration'], 0)
        self.assertEqual(row['frames'], [])
        self.assertEqual(result['media_count'], 1)
        with patch.object(analysis, 'probe', side_effect=RuntimeError('synthetic retry')) as probe:
            self.analyze()
        probe.assert_called_once()

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),
                         'Set VIDEO_EDIT_FFMPEG/FFPROBE for real cache integration')
    def test_real_decoder_mixed_hits_sampling_change_and_deletion(self):
        from video_edit.common import run
        ffmpeg, ffprobe = os.environ['VIDEO_EDIT_FFMPEG'], os.environ['VIDEO_EDIT_FFPROBE']
        cfg = dict(self.cfg, ffmpeg=ffmpeg, ffprobe=ffprobe)
        def make(name, color):
            run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                 f'color=c={color}:s=64x36:r=25:d=4', '-c:v', 'libx264',
                 '-pix_fmt', 'yuv420p', '-an', '-y', self.media/name])
        make('a.mp4', 'red'); make('b.mp4', 'blue')
        first = self.analyze(cfg, transcribe=False)
        self.assertEqual(first['ready_count'], 2)
        make('a.mp4', 'green')
        mixed = self.analyze(cfg, transcribe=False)
        self.assertEqual(len(read(mixed['inventory'])), 2)
        self.assertEqual(mixed['cache']['visual'], {'hits': 1, 'runs': 1})
        dense = self.analyze(dict(cfg, sample_interval_seconds=.5), transcribe=False)
        self.assertEqual(dense['cache']['visual']['runs'], 2)
        self.assertEqual([len(r['frames']) for r in read(dense['inventory'])], [8, 8])
        (self.media/'a.mp4').unlink()
        deleted = self.analyze(dict(cfg, sample_interval_seconds=.5), transcribe=False)
        self.assertEqual([r['filename'] for r in read(deleted['inventory'])], ['b.mp4'])


if __name__ == '__main__': unittest.main()

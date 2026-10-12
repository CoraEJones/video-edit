"""MP4-only regression tests, including a real optional FFmpeg render.

Set VIDEO_EDIT_FFMPEG and VIDEO_EDIT_FFPROBE to run the integration test.
Set VIDEO_EDIT_QA_ROOT to keep all generated fixtures outside the repository.
Review declarations describe synthetic fixtures, not listening to real footage.
"""
import builtins
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.common import EditError, read, run, sha256, write
from video_edit.assets import prepare_assets, verify_referenced_sources
from video_edit.mp4 import export


class Mp4ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('VIDEO_EDIT_QA_ROOT'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_reference_mode_never_copies_originals_and_detects_changes(self):
        from PIL import Image
        source = self.root / 'source.png'
        Image.new('RGB', (64, 36), 'blue').save(source)
        folder = self.root / 'delivery'
        rows = [{'id': 'photo', 'kind': 'image', 'absolute_path': str(source), 'duration': 0}]
        plan = {'width': 64, 'height': 36, 'shots': [{'id': 'photo'}]}
        assets = prepare_assets(plan, rows, folder, {}, copy_originals=False)
        self.assertEqual(Path(assets['photo']['video']), source)
        self.assertFalse((folder / 'assets/originals').exists())
        verify_referenced_sources(folder)
        Image.new('RGB', (64, 36), 'green').save(source)
        with self.assertRaises(EditError) as error:
            verify_referenced_sources(folder)
        self.assertEqual(error.exception.code, 'SOURCE_CHANGED')

    def test_native_default_still_makes_portable_byte_identical_copy(self):
        from PIL import Image
        source = self.root / 'source.png'
        Image.new('RGB', (64, 36), 'blue').save(source)
        folder = self.root / 'editable'
        rows = [{'id': 'photo', 'kind': 'image', 'absolute_path': str(source), 'duration': 0}]
        assets = prepare_assets({'width': 64, 'height': 36, 'shots': [{'id': 'photo'}]}, rows, folder, {})
        copied = Path(assets['photo']['original'])
        self.assertTrue(copied.is_relative_to(folder / 'assets/originals'))
        self.assertEqual(sha256(source), sha256(copied))
        self.assertTrue(read(folder / 'source-manifest.json')[0]['copied'])

    def test_existing_output_is_never_reused(self):
        plan = self.root / 'plan.json'
        write(plan, {'name': 'existing'})
        (self.root / 'existing').mkdir()
        marker = self.root / 'existing' / 'old.mp4'
        marker.write_bytes(b'previous result')
        with patch('video_edit.mp4.validate', return_value={'valid': True}), \
                patch('video_edit.intake.require_delivery_request'):
            with self.assertRaises(EditError) as error:
                export(plan, self.root, {})
        self.assertEqual(error.exception.code, 'OUTPUT_EXISTS')
        self.assertEqual(marker.read_bytes(), b'previous result')

    def test_incomplete_request_stops_before_making_output(self):
        plan = self.root / 'plan.json'
        write(plan, {'name': 'missing_details'})
        with self.assertRaises(EditError) as error:
            export(plan, self.root / 'delivery', {})
        self.assertEqual(error.exception.code, 'REQUEST_INCOMPLETE')
        self.assertFalse((self.root / 'delivery').exists())

    def test_final_acceptance_rejects_missing_or_truncated_mix_and_wrong_fps(self):
        from video_edit.stream_render import verify_streams
        plan = {'width': 640, 'height': 360, 'fps': 25, 'duration': 4}
        measured = {'streams': [
            {'codec_type': 'video', 'width': 640, 'height': 360, 'nb_frames': '100', 'avg_frame_rate': '25/1'},
            {'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '48000', 'channels': 2,
             'duration': '4.000', 'start_time': '0.000'}]}
        self.assertEqual(verify_streams(measured, plan), 100)
        missing = copy.deepcopy(measured)
        missing['streams'].pop()
        truncated = copy.deepcopy(measured)
        truncated['streams'][1]['duration'] = '3.5'
        drifted = copy.deepcopy(measured)
        drifted['streams'][0]['avg_frame_rate'] = '24/1'
        for incorrect in (missing, truncated, drifted):
            with self.assertRaises(RuntimeError):
                verify_streams(incorrect, plan)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),
                         'Set FFmpeg/FFprobe environment paths for the real no-editor smoke test')
    def test_real_mp4_without_editor_renders_all_layers_at_full_quality(self):
        from PIL import Image
        import numpy as np
        from video_edit.common import probe
        ffmpeg, ffprobe = os.environ['VIDEO_EDIT_FFMPEG'], os.environ['VIDEO_EDIT_FFPROBE']
        media = self.root / 'media'
        media.mkdir()
        source = media / 'source.mp4'
        # Test footage intentionally contains a loud tone. No original-audio
        # approval is given, so only the independent music layer may be audible.
        run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=red:s=640x360:r=25:d=2',
             '-f', 'lavfi', '-i', 'sine=frequency=3000:sample_rate=48000:duration=2',
             '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', '-y', source])
        rows = [dict(probe(source, {'ffprobe': ffprobe}), id='video', kind='video',
                     absolute_path=str(source), has_audio=True, transcription_status='done')]
        for color in ('red', 'green', 'blue'):
            path = media / (color + '.png')
            Image.new('RGB', (640, 360), color).save(path)
            rows.append({'id': color, 'kind': 'image', 'absolute_path': str(path),
                         'width': 640, 'height': 360, 'duration': 0})
        layer = media / 'transparent.png'
        overlay = Image.new('RGBA', (160, 80))
        overlay.paste((255, 255, 0, 255), (40, 0, 120, 80))
        overlay.save(layer)
        rows.append({'id': 'overlay', 'kind': 'image', 'absolute_path': str(layer),
                     'width': 160, 'height': 80, 'duration': 0})
        before = {r['absolute_path']: sha256(r['absolute_path']) for r in rows}
        def shot(index, ident, start, duration, speed=1, **kw):
            return dict(index=index, id=ident, start=start, duration=duration,
                        source_in=0, speed=speed, audio_gain=0, **kw)
        plan = {'name': '无剪映完整导出', 'width': 640, 'height': 360, 'fps': 25, 'duration': 4,
                'inventory': rows, 'review': {'status': 'reviewed',
                    'evidence': 'Synthetic generated color fixtures, known pixel and tone expectations.'},
                'request': {'music': '自动配乐', 'voiceover': False, 'subtitles': True,
                            'quality_policy': 'preserve_source', 'rhythm': '温馨舒缓', 'text_style': '清爽现代'},
                'shots': [shot(1, 'video', 0, 1.2, .5),
                          shot(2, 'black', 1.2, 1.2, purpose='panels_test'),
                          shot(3, 'blue', 2.4, 1.6, fade_out=.6)],
                'panels': [shot(2, c, 1.2, 1.2, panel=i) for c, i in zip(('red', 'green', 'blue'), (-1, 0, 1))],
                'mask_reveal': {'start': 0, 'duration': .4, 'hold': .08},
                'visual_layers': [{'id': 'overlay', 'start': .4, 'duration': .8, 'scale': .25,
                    'keyframes': [{'time': 0, 'x': -.7, 'y': .1}, {'time': .76, 'x': .7, 'y': .1}]}],
                'titles': [{'text': '一路向海', 'start': .4, 'end': 1.12, 'size': 100,
                            'color': '#FFFFFF', 'y': -.4, 'font_id': 'ZhiMangXing-Regular/ZhiMangXing-Regular.ttf'}],
                'captions': [{'zh': '把此刻留下', 'start': 1.28, 'end': 3.0, 'size': 6}],
                'techniques': ['split_screen', 'mask_reveal', 'visual_layers', 'fade']}
        plan_path = self.root / 'plan.json'
        from video_edit.intake import DEFAULTS, confirm_request
        request = dict(DEFAULTS, **plan['request'])
        request.update(media_dir=str(media), output_dir=str(self.root / 'delivery'),
                       delivery_mode='mp4', name=plan['name'], target_seconds=None)
        # Explicit synthetic fixture approval, never approval for a user's film.
        plan['request'] = confirm_request(request, True)
        write(plan_path, plan)
        font = Path(__file__).resolve().parents[1] / 'assets/fonts/ZhiMangXing-Regular/ZhiMangXing-Regular.ttf'
        if not font.is_file():
            font = next((Path(__file__).resolve().parents[1] / 'assets/fonts').rglob('ZhiMangXing-Regular.ttf'))
        # No config discovery: not one editor, mask, DLL, or Harness path exists.
        cfg = {'ffmpeg': ffmpeg, 'ffprobe': ffprobe, 'font_path': str(font), 'font_dirs': [],
               'ffmpeg_threads': 2, 'preview_mode': 'draft', 'preview_width': 160}
        original_import = builtins.__import__
        def without_editor(name, *args, **kwargs):
            if name.startswith('pyJianYingDraft') or name in ('native', 'video_edit.native'):
                raise AssertionError('Standalone MP4 attempted editor import: ' + name)
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_editor):
            result = export(plan_path, self.root / 'delivery', cfg)
        folder, movie = Path(result['output_path']), Path(result['movie'])
        self.assertTrue(movie.is_file())
        self.assertFalse(result['requires_jianying'])
        self.assertEqual(result['quality']['frame_count'], 100)
        self.assertEqual((result['quality']['width'], result['quality']['height']), (640, 360))
        self.assertFalse(result['quality']['intermediate_compressed'])
        self.assertEqual(result['quality']['lossy_video_encodes_per_output_frame'], 1)
        self.assertFalse((folder / 'draft_content.json').exists())
        self.assertFalse((folder / 'assets/originals').exists())
        self.assertFalse(list(folder.rglob('*.mkv')))
        self.assertFalse(list(folder.rglob('*完整原声.wav')))
        for path, digest in before.items():
            self.assertEqual(sha256(path), digest)
        self.assertTrue(result['srt'])
        self.assertIn('把此刻留下', Path(result['srt'][0]).read_text(encoding='utf-8-sig'))
        def frame(t):
            raw = run([ffmpeg, '-v', 'error', '-ss', t, '-i', movie, '-frames:v', 1,
                       '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']).stdout
            return np.frombuffer(raw, np.uint8).reshape(360, 640, 3)
        self.assertLess(float(frame(0).mean()), 3)  # closed top/bottom curtain
        panels = frame(1.6)
        for x, channel in ((109, 0), (320, 1), (531, 2)):
            pixel = panels[180, x]
            self.assertGreater(int(pixel[channel]), max(int(v) for j, v in enumerate(pixel) if j != channel) + 70)
        first = frame(.8)
        yellow = (first[:, :, 0] > 180) & (first[:, :, 1] > 180) & (first[:, :, 2] < 60)
        self.assertGreater(int(yellow.sum()), 800)  # transparent moving layer survived
        self.assertGreater(int(((first[:, :, :].min(axis=2) > 180) & (np.indices((360, 640))[0] > 190)).sum()), 100)
        self.assertLess(int(frame(3.96)[180, 320, 2]), 30)  # slow ending fades out
        audio = np.frombuffer(run([ffmpeg, '-v', 'error', '-i', movie, '-vn', '-f', 'f32le',
                                   '-ac', 1, '-ar', 48000, 'pipe:1']).stdout, '<f4')
        self.assertGreater(float(np.sqrt(np.mean(audio ** 2))), .003)  # music present
        spectrum = np.abs(np.fft.rfft(audio[:48000]))
        self.assertLess(float(spectrum[2995:3006].max()), float(spectrum.max()) * .03)  # source tone muted


if __name__ == '__main__':
    unittest.main()

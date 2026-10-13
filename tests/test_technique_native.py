"""Native draft structure/codec invariants; never imply editor visual QA."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from video_edit.common import EditError, read, run, sha256
from video_edit.technique_native import capabilities, export_native, resource_for, transform_samples


class TechniqueNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('VIDEO_EDIT_QA_ROOT'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '原生 with spaces'; self.root.mkdir()
        self.font = ROOT / 'assets/fonts/ZhiMangXing-Regular/ZhiMangXing-Regular.ttf'
        self.cfg = {'font_path': str(self.font), 'ffmpeg': os.environ.get('VIDEO_EDIT_FFMPEG'),
                    'ffprobe': os.environ.get('VIDEO_EDIT_FFPROBE'),
                    'jianying_install_dir': os.environ.get('VIDEO_EDIT_JIANYING_INSTALL'),
                    'jianying_user_data': os.environ.get('VIDEO_EDIT_JIANYING_USER_DATA')}
        self.spec = {'schema_version': 'technique.2.0', 'input_space': 'bt709_sdr',
            'canvas': {'width': 160, 'height': 96, 'fps': 25, 'duration': .4, 'background_opacity': 0},
            'layers': [{'id': 'red', 'source': {'kind': 'solid', 'color': '#FF0000'}, 'duration': .4}]}

    def test_capability_rejects_unknown_fields_and_never_labels_fallback_native(self):
        spec = copy.deepcopy(self.spec); spec['layers'][0]['magic_effect_id'] = 'invented'
        self.assertFalse(capabilities(spec, self.root, self.cfg, inspect_files=False)['valid'])
        spec = copy.deepcopy(self.spec); spec['layers'][0]['blend'] = 'addition'
        report = capabilities(spec, self.root, self.cfg, inspect_files=False)
        self.assertTrue(report['valid']); self.assertFalse(report['native'])
        self.assertIn('MixModeType', report['layers'][0]['unsupported'][0])
        with self.assertRaises(EditError) as raised:
            export_native(spec, self.root, self.cfg, self.root / 'must-not-exist')
        self.assertEqual(raised.exception.code, 'NATIVE_TECHNIQUE_UNSUPPORTED')
        self.assertFalse((self.root / 'must-not-exist').exists())

    def test_actual_resource_required_not_only_enum_id(self):
        self.assertIsNone(resource_for('rect', {}))
        fake = self.root / 'fake-mask'; fake.mkdir()
        (fake / 'config.json').write_text('{"name":"rect","effect":{}}')
        self.assertIsNone(resource_for('rect', {'native_mask_dirs': {'rect': str(fake)}}))
        spec = copy.deepcopy(self.spec); spec['layers'][0]['mask'] = {'type': 'rect'}
        with patch('video_edit.technique_native.resource_for', return_value=None):
            report = capabilities(spec, self.root, self.cfg, inspect_files=False)
        self.assertFalse(report['native'])
        self.assertIn('resource is missing', report['layers'][0]['unsupported'][0])

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG') and os.environ.get('VIDEO_EDIT_FFPROBE'),'Set actual FFmpeg paths')
    def test_anamorphic_source_requires_display_geometry_derivation(self):
        source=self.root/'sar.mov'
        run([self.cfg['ffmpeg'],'-v','error','-f','lavfi','-i','color=red:s=160x96:r=25:d=0.4','-vf','setsar=2/1','-an','-c:v','qtrle','-y',source])
        spec=copy.deepcopy(self.spec);spec['layers']=[{'id':'sar','source':{'path':str(source)},'duration':.4}]
        report=capabilities(spec,self.root,self.cfg)
        self.assertTrue(report['valid']);self.assertFalse(report['native'])
        self.assertTrue(any('sample_aspect_ratio' in value for value in report['layers'][0]['unsupported']))

    def test_curve_and_pixel_feather_never_silently_approximated(self):
        spec = copy.deepcopy(self.spec)
        spec['layers'][0]['mask'] = {'type': 'linear', 'progress': [{'time': 0, 'value': 0}, {'time': .36, 'value': 1}], 'feather_px': 12}
        with patch('video_edit.technique_native.resource_for', return_value=self.root):
            report = capabilities(spec, self.root, self.cfg, inspect_files=False)
        self.assertFalse(report['native'])
        text = ' '.join(report['layers'][0]['unsupported'])
        self.assertIn('pixel feather', text); self.assertIn('keyframe API', text)

    def test_smoothstep_and_fade_product_are_sampled_at_output_frames(self):
        layer = {'opacity': .8, 'fade_in': .2, 'fade_out': .2, 'easing': 'smoothstep',
                 'keyframes': [{'time': 0, 'x': -1, 'opacity': .8}, {'time': .36, 'x': 1, 'opacity': .4}]}
        samples = transform_samples(layer, 25, .4)
        self.assertEqual(len(samples), 10)
        self.assertEqual(samples[0]['opacity'], 0)
        self.assertAlmostEqual(samples[-1]['x'], 1)
        self.assertAlmostEqual(samples[-1]['opacity'], .08)
        q = (.08 / .36); expected = -1 + 2 * q * q * (3 - 2 * q)
        self.assertAlmostEqual(samples[2]['x'], expected)
        self.assertEqual(samples[2]['scale'], 1)

    def test_text_alpha_animation_and_glow_have_explicit_gaps(self):
        spec = copy.deepcopy(self.spec)
        spec['layers'][0]['source'] = {'kind': 'text', 'text': '标题', 'font_path': str(self.font), 'glow_radius_px': 4}
        spec['layers'][0]['keyframes'] = [{'time': 0, 'opacity': 0}, {'time': .36, 'opacity': 1}]
        report = capabilities(spec, self.root, self.cfg, inspect_files=False)
        self.assertFalse(report['native'])
        self.assertEqual(len(report['layers'][0]['unsupported']), 2)
        self.assertTrue(report['layers'][0]['approximations'])

    def decoded(self, folder):
        from pyJianYingDraft.draft_codec import load_json_object_with_codec
        from video_edit.native import codec
        obj, encrypted = load_json_object_with_codec(folder / 'draft_content.json', content_codec=codec(self.cfg))
        self.assertTrue(encrypted)
        return obj

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_JIANYING_INSTALL') and os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set real local editor/FFmpeg paths')
    def test_real_encrypted_independent_tracks_keyframes_masks_and_fonts(self):
        spec = copy.deepcopy(self.spec)
        spec['canvas']['duration'] = .8
        spec['layers'][0].update(start=.2, duration=.4,
            keyframes=[{'time': 0, 'x': -.4, 'scale': .8, 'rotation': -5, 'opacity': .4},
                       {'time': .36, 'x': .4, 'scale': 1.2, 'rotation': 5, 'opacity': 1}],
            mask={'type': 'rect', 'width': .5, 'height': .4, 'invert': True})
        spec['layers'].append({'id': 'words', 'source': {'kind': 'text', 'text': '代码剪辑', 'font_path': str(self.font),
                               'font_size_px': 30, 'stroke_px': 1, 'stroke_color': '#112233'}, 'duration': .8, 'y': -.6})
        cap = capabilities(spec, self.root, self.cfg)
        if not cap['native']: self.skipTest('Actual rectangle mask resource missing')
        folder = self.root / 'native'; report = export_native(spec, self.root, self.cfg, folder)
        obj = self.decoded(folder)
        self.assertEqual(obj['duration'], 800000)
        self.assertEqual(len(obj['tracks']), 3)
        segments = [seg for track in obj['tracks'] for seg in track['segments']]
        red = next(seg for seg in segments if seg['id'] == report['tracks'][0]['segment_id'])
        self.assertEqual(red['target_timerange'], {'start': 200000, 'duration': 400000})
        keys = {key['property_type']: key['keyframe_list'] for key in red['common_keyframes']}
        self.assertEqual(set(keys), {'KFTypePositionX', 'KFTypeScaleX', 'KFTypeRotation', 'KFTypeAlpha'})
        self.assertEqual(keys['KFTypePositionX'][-1]['values'], [.4])
        self.assertEqual(keys['KFTypePositionX'][-1]['time_offset'], 360000)
        mask = obj['materials']['common_mask'][0]
        self.assertIn(mask['id'], red['extra_material_refs'])
        self.assertTrue(Path(mask['path']).is_dir()); self.assertTrue(mask['config']['invert'])
        self.assertAlmostEqual(mask['config']['width'], .5)
        material = obj['materials']['texts'][0]; text = json.loads(material['content'])
        self.assertEqual(text['text'], '代码剪辑'); self.assertTrue(text['styles'][0]['strokes'])
        self.assertTrue(Path(text['styles'][0]['font']['path']).is_file())
        self.assertEqual(sha256(text['styles'][0]['font']['path']), sha256(self.font))
        self.assertTrue(report['encrypted_roundtrip']); self.assertFalse(report['registered']); self.assertFalse(report['ui_verified'])
        self.assertTrue(report['native_effect_parameters_editable'])

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_JIANYING_INSTALL') and os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set real local editor/FFmpeg paths')
    def test_real_freeze_generated_png_and_original_identity(self):
        movie = self.root / 'source.mkv'
        frames = b''.join(bytes(color) * (160 * 96) for color in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)])
        run([self.cfg['ffmpeg'], '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '160x96',
             '-framerate', '25', '-i', 'pipe:0', '-c:v', 'ffv1', '-pix_fmt', 'bgra', '-n', movie], input=frames)
        before = sha256(movie)
        self.spec['layers'] = [{'id': 'hold', 'source': {'path': str(movie)}, 'freeze_at': .08, 'duration': .4}]
        folder = self.root / 'freeze'; report = export_native(self.spec, self.root, self.cfg, folder)
        obj = self.decoded(folder)
        held = next(x for x in obj['materials']['videos'] if 'freeze-' in x['path'])
        self.assertEqual(held['type'], 'photo')
        self.assertEqual(Image.open(held['path']).convert('RGB').getpixel((80, 48)), (0, 0, 255))
        self.assertEqual(sha256(movie), before)
        self.assertTrue(report['layers'][0]['generated_sources'])

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_JIANYING_INSTALL') and os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set real local editor/FFmpeg paths')
    def test_real_complex_fallback_is_explicitly_single_baked_composition(self):
        spec = copy.deepcopy(self.spec)
        spec['layers'].append({'id': 'blue', 'source': {'kind': 'solid', 'color': '#0000FF'}, 'duration': .4, 'blend': 'addition'})
        folder = self.root / 'fallback'; report = export_native(spec, self.root, self.cfg, folder, allow_derived=True)
        obj = self.decoded(folder)
        self.assertEqual(len(obj['tracks']), 2)  # background + explicit baked composition
        self.assertEqual(report['route'], 'derived_composition')
        self.assertFalse(report['native_effect_parameters_editable'])
        self.assertTrue(report['tracks'][0]['baked_composition'])
        self.assertTrue(report['derived_render']['full_decode_verified'])
        self.assertFalse(report['ui_verified'])
        media = next(x for x in obj['materials']['videos'] if x['path'].endswith('asset.mov'))
        pixel = run([self.cfg['ffmpeg'], '-v', 'error', '-i', media['path'], '-frames:v', '1', '-pix_fmt', 'rgba', '-f', 'rawvideo', 'pipe:1']).stdout
        self.assertEqual(tuple(pixel[(48 * 160 + 80) * 4:(48 * 160 + 80) * 4 + 4]), (255, 0, 255, 255))

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_JIANYING_INSTALL') and os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set real local editor/FFmpeg paths')
    def test_real_local_fallback_retains_independent_native_tracks_and_transforms(self):
        spec = copy.deepcopy(self.spec)
        spec['layers'].append({'id': 'masked_blue', 'source': {'kind': 'solid', 'color': '#0000FF'},
            'duration': .4, 'mask': {'type': 'rect', 'width': .5, 'height': .5, 'feather_px': 4},
            'keyframes': [{'time': 0, 'x': -.3, 'opacity': .5}, {'time': .36, 'x': .3, 'opacity': 1}]})
        folder = self.root / 'partial'; report = export_native(spec, self.root, self.cfg, folder, allow_derived=True)
        obj = self.decoded(folder)
        self.assertEqual(report['route'], 'hybrid_layers')
        self.assertFalse(report['native_effect_parameters_editable'])
        self.assertTrue(report['native_layer_transforms_editable'])
        self.assertEqual(len(obj['tracks']), 3)
        self.assertFalse(report['tracks'][0]['baked_layer_operations'])
        self.assertTrue(report['tracks'][1]['baked_layer_operations'])
        self.assertFalse(report['tracks'][1]['baked_composition'])
        segment = next(seg for track in obj['tracks'] for seg in track['segments']
                       if seg['id'] == report['tracks'][1]['segment_id'])
        properties = {key['property_type'] for key in segment['common_keyframes']}
        self.assertEqual(properties, {'KFTypePositionX', 'KFTypeAlpha'})
        alpha_path = report['derived_layers']['masked_blue']['output']
        pixels = run([self.cfg['ffmpeg'], '-v', 'error', '-i', alpha_path, '-frames:v', '1', '-pix_fmt', 'rgba', '-f', 'rawvideo', 'pipe:1']).stdout
        self.assertEqual(pixels[3], 0)
        offset = (48 * 160 + 80) * 4
        self.assertEqual(tuple(pixels[offset:offset + 4]), (0, 0, 255, 255))


if __name__ == '__main__':
    unittest.main()

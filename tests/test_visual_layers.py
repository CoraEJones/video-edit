"""Pure validation tests; no editor, media files, or machine paths required."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.visual_layers import normalize, validate_visual_layers


class VisualLayersTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'fps': 25, 'duration': 4, 'visual_layers': [{
            'id': 'photo', 'start': .4, 'duration': 2, 'scale': .45,
            'keyframes': [{'time': 0, 'x': -1.4, 'y': 0},
                          {'time': .8, 'x': 0, 'y': 0},
                          {'time': 1.96, 'x': 1.4, 'y': 0}]}]}
        self.lookup = {'photo': {'kind': 'image', 'duration': 0},
                       'video': {'kind': 'video', 'duration': 5}}

    def errors(self, plan=None):
        errors = []
        selected = set()
        validate_visual_layers(plan or self.plan, self.lookup, selected,
            lambda code, at, message: errors.append(code))
        return errors, selected

    def test_frame_aligned_motion_and_asset_selection(self):
        errors, selected = self.errors()
        self.assertEqual(errors, [])
        self.assertEqual(selected, {'photo'})

    def test_last_visible_frame_required(self):
        self.plan['visual_layers'][0]['keyframes'][-1]['time'] = 2
        self.assertIn('VISUAL_KEYFRAME_END', self.errors()[0])

    def test_start_frame_and_strict_order(self):
        keys = self.plan['visual_layers'][0]['keyframes']
        keys[0]['time'] = .04
        keys[1]['time'] = .04
        errors, _ = self.errors()
        self.assertIn('VISUAL_KEYFRAME_START', errors)
        self.assertIn('VISUAL_KEYFRAME_TIME', errors)

    def test_single_frame_layer_can_have_one_keyframe(self):
        layer = self.plan['visual_layers'][0]
        layer.update(duration=1/25, keyframes=[{'time': 0, 'x': 0, 'y': 0}])
        self.assertEqual(self.errors()[0], [])

    def test_unknown_fields_are_rejected(self):
        self.plan['visual_layers'][0]['opacity'] = .5
        self.assertIn('VISUAL_FIELD', self.errors()[0])

    def test_unknown_asset_and_bad_id_type(self):
        for ident in ('missing', [], None):
            with self.subTest(ident=ident):
                self.plan['visual_layers'][0]['id'] = ident
                self.assertIn('UNKNOWN_ASSET', self.errors()[0])

    def test_video_source_range_uses_speed(self):
        layer = self.plan['visual_layers'][0]
        layer.update(id='video', source_in=2, speed=2)
        self.assertIn('SOURCE_OVERFLOW', self.errors()[0])
        layer.update(source_in=1)
        self.assertEqual(self.errors()[0], [])

    def test_image_source_range_is_fixed(self):
        layer = self.plan['visual_layers'][0]
        layer.update(speed=.5)
        self.assertIn('VISUAL_IMAGE_RANGE', self.errors()[0])

    def test_end_time_and_start_frame(self):
        layer = self.plan['visual_layers'][0]
        layer.update(start=3.01)
        errors, _ = self.errors()
        self.assertIn('VISUAL_TIME', errors)
        self.assertIn('VISUAL_FRAME', errors)

    def test_no_nonfinite_or_out_of_range_values(self):
        for field, value, code in [('scale', float('nan'), 'VISUAL_NUMBER'),
                                   ('scale', 0, 'VISUAL_SCALE'), ('x', 5, 'VISUAL_POSITION')]:
            with self.subTest(field=field, value=value):
                plan = copy.deepcopy(self.plan)
                plan['visual_layers'][0][field] = value
                self.assertIn(code, self.errors(plan)[0])

    def test_keyframes_only_accept_time_and_xy(self):
        self.plan['visual_layers'][0]['keyframes'][0]['easing'] = 'ease'
        self.assertIn('VISUAL_KEYFRAME', self.errors()[0])

    def test_static_layer_defaults_and_no_mutation(self):
        layer = {'id': 'photo', 'start': 0, 'duration': 4}
        original = copy.deepcopy(layer)
        self.assertEqual(normalize(layer)['scale'], 1)
        self.assertEqual(layer, original)
        self.plan['visual_layers'] = [layer]
        self.assertEqual(self.errors()[0], [])


if __name__ == '__main__':
    unittest.main()

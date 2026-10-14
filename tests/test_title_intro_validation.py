"""Real PNG counterexamples with explicit mocked video metadata.

These unit checks do not claim media decoding; synthetic-self-test covers that.
"""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import render_titles as title
from title_qa_example import generate


class TitleIntroValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'mock-probed-source.mp4'
        self.source.write_bytes(b'Not decoded: metadata is explicitly mocked in this unit test')
        self.art = self.root / 'art.png'
        image = Image.new('RGBA', (100, 100))
        ImageDraw.Draw(image).rectangle((30, 30, 69, 69), fill='white')
        image.save(self.art)
        self.design = {'schema_version': 'title-intro.1.0', 'id': 'fixture', 'title_text': 'synthetic strokes',
                       'source': {'path': str(self.source), 'duration_s': 4},
                       'canvas': {'width': 200, 'height': 200, 'fps': 60},
                       'title': {'path': str(self.art), 'x_px': -10, 'y_px': -10, 'width_px': 100,
                                 'start_s': .25, 'end_s': 3.75}}
        self.meta = {'duration': 8, 'width': 200, 'height': 200, 'rotation': 0,
                     'sample_aspect_ratio': '1:1', 'color_transfer': None}

    def validate(self, design=None):
        with patch.object(title, 'probe', return_value=self.meta):
            return title.validate_design(self.design if design is None else design, self.root, {})

    def test_package_uses_its_own_modules_and_alpha_safety_not_png_outer_edge(self):
        self.assertEqual(title.DEFAULT_SKILL, ROOT)
        self.assertEqual(title.ROOT, ROOT)
        resolved = self.validate()
        self.assertEqual(resolved['layers'][0]['visible_bbox_at_rest_px'], [20, 20, 60, 60])
        self.assertNotIn('metadata', self.design['source'])

    def test_real_alpha_and_margin_failures(self):
        opaque = Image.new('RGBA', (100, 100), 'white')
        opaque.save(self.art)
        with self.assertRaisesRegex(ValueError, 'visible and transparent'):
            self.validate()
        transparent = Image.new('RGBA', (100, 100))
        transparent.save(self.art)
        with self.assertRaisesRegex(ValueError, 'visible and transparent'):
            self.validate()

    def test_input_fingerprint_source_hash_not_metadata_name(self):
        d = deepcopy(self.design)
        d['source']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            self.validate(d)

    def test_source_bounds_and_frame_alignment(self):
        d = deepcopy(self.design)
        d['source']['source_in_s'] = 5
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            self.validate(d)
        d = deepcopy(self.design)
        d['title']['start_s'] = .251
        with self.assertRaisesRegex(ValueError, 'project frames'):
            self.validate(d)

    def test_curve_endpoint_and_unbounded_recoil_are_rejected(self):
        d = deepcopy(self.design)
        d['title']['motion'] = {'type': 'curved_path', 'cubic_bezier_points_px': [[0, 0], [5, 0], [10, 0], [1, 0]]}
        with self.assertRaisesRegex(ValueError, 'end at'):
            self.validate(d)
        d['title']['motion'] = {'type': 'rotate_settle', 'overshoot_px': 5}
        with self.assertRaisesRegex(ValueError, 'positive settle_s'):
            self.validate(d)

    def test_missing_characters_unknown_motion_and_known_hdr_are_not_success(self):
        d = deepcopy(self.design)
        d['title_text'] = ''
        with self.assertRaisesRegex(ValueError, 'title_text'):
            self.validate(d)
        d = deepcopy(self.design)
        d['title']['motion'] = {'type': 'invented_handwriting'}
        with self.assertRaisesRegex(ValueError, 'Unknown motion'):
            self.validate(d)
        self.meta['color_transfer'] = 'smpte2084'
        with self.assertRaisesRegex(ValueError, 'HDR source'):
            self.validate()

    def test_qa_example_is_runnable_without_editor_and_refuses_overwrite(self):
        directory = self.root / 'qa-example'
        result = generate(directory)
        self.assertTrue(Path(result['report']).is_file())
        self.assertEqual(result['human_visual_review_status'], 'pending')
        with self.assertRaises(FileExistsError):
            generate(directory)


if __name__ == '__main__':
    unittest.main()

"""Pixel-level invariants for local font-based text assets."""
import sys
import unittest
from pathlib import Path

from PIL import ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from video_edit.text_raster import render_text

FONT = ROOT / 'assets/fonts/ZhiMangXing-Regular/ZhiMangXing-Regular.ttf'


def pixels(image):
    values = iter(image.tobytes())
    return zip(values, values, values, values)


class TextRasterTests(unittest.TestCase):
    def render(self, **kwargs):
        options = dict(canvas_size=(640, 360), text='文字 Video', font_path=FONT, font_size_px=56)
        options.update(kwargs)
        return render_text(**options)

    def test_transparent_full_canvas_and_centered_ink(self):
        image = self.render()
        self.assertEqual((image.mode, image.size), ('RGBA', (640, 360)))
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        left, top, right, bottom = image.getchannel('A').getbbox()
        self.assertAlmostEqual((left + right) / 2, 320, delta=3)
        self.assertAlmostEqual((top + bottom) / 2, 180, delta=3)
        self.assertTrue(0 < left < right < 640 and 0 < top < bottom < 360)

    def test_core_stroke_and_glow_have_distinct_pixels(self):
        base = self.render(text='Video', color='#F02060', stroke_px=3, stroke_color='#102040')
        glow = self.render(text='Video', color='#F02060', stroke_px=3,
                           stroke_color='#102040', glow_radius_px=6, glow_opacity=0.6)
        self.assertTrue(any(pixel == (240, 32, 96, 255) for pixel in pixels(base)))
        self.assertTrue(any(pixel == (16, 32, 64, 255) for pixel in pixels(base)))
        edge = [p for b, p in zip(pixels(base), pixels(glow)) if b[3] == 0 and p[3] > 0]
        self.assertTrue(edge)
        self.assertTrue(all(p[:3] == (240, 32, 96) for p in edge))
        self.assertTrue(all(0 < p[3] < 255 for p in edge))
        self.assertEqual(glow.getpixel((0, 0))[3], 0)

    def test_zero_glow_preserves_raster(self):
        plain = self.render()
        self.assertEqual(plain.tobytes(), self.render(glow_radius_px=9, glow_opacity=0).tobytes())

    def test_unicode_and_multiline_preserve_font_scale(self):
        one = self.render(text='你好世界', font_size_px=48)
        multi = self.render(text='你好世界\nVideo', font_size_px=48)
        a, b = one.getchannel('A').getbbox(), multi.getchannel('A').getbbox()
        self.assertGreater(b[3] - b[1], a[3] - a[1])
        self.assertAlmostEqual(b[2] - b[0], a[2] - a[0], delta=2)
        face = ImageFont.truetype(str(FONT), 48)
        self.assertTrue(all(face.getmask(char).getbbox() for char in '你好世界'))

    def test_missing_font_does_not_fallback(self):
        with self.assertRaises(FileNotFoundError):
            self.render(font_path=FONT.parent / 'missing.ttf')

    def test_oversized_text_is_not_cropped_or_shrunk(self):
        with self.assertRaisesRegex(ValueError, 'fit canvas'):
            self.render(canvas_size=(64, 32), text='Long title', font_size_px=60)
        with self.assertRaisesRegex(ValueError, 'fit canvas'):
            self.render(canvas_size=(640, 50), text='first\nsecond', font_size_px=48)

    def test_strict_finite_ranges_and_pixel_budget(self):
        cases = [dict(canvas_size=(16_384, 16_384)), dict(canvas_size=(0, 20)),
                 dict(canvas_size=(20.0, 30)), dict(font_size_px=True),
                 dict(font_size_px=float('inf')), dict(stroke_px=-1),
                 dict(stroke_px=1.5), dict(glow_radius_px=float('nan')),
                 dict(glow_radius_px=float('inf')), dict(glow_opacity=-0.1),
                 dict(glow_opacity=1.1), dict(glow_opacity=True),
                 dict(color='white'), dict(stroke_color='#fff'),
                 dict(text='x' * 501), dict(text=' \n '), dict(text='a\tb')]
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.render(**values)


if __name__ == '__main__':
    unittest.main()

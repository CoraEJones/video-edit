"""Synthetic pixel counterexamples; no user media or inferred subjects."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "visual_qa.py"
SPEC = importlib.util.spec_from_file_location("visual_qa", MODULE_PATH)
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


class PixelQA(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.background = self.directory / "background.png"
        self.title = self.directory / "title.png"
        Image.new("RGB", (100, 80), (0, 0, 0)).save(self.background)
        artwork = Image.new("RGBA", (20, 20), (255, 255, 255, 0))
        ImageDraw.Draw(artwork).rectangle((5, 5, 14, 14), fill=(255, 255, 255, 255))
        artwork.save(self.title)
        self.request = {
            "schema_version": qa.SCHEMA,
            "canvas": {"width_px": 100, "height_px": 80},
            "title_image": str(self.title),
            "transform": {"x_px": 20, "y_px": 10, "width_px": 20, "height_px": 20},
            "safe_margin_px": {"left": 10, "right": 10, "top": 10, "bottom": 10},
            "frames": [{"path": str(self.background), "source_time_s": 2.5, "label": "middle"}],
        }

    def tearDown(self):
        self.temp.cleanup()

    def report(self, request=None):
        return qa.inspect_title(self.request if request is None else request)

    def test_exact_alpha_placement_and_black_white_contrast(self):
        report = self.report()
        frame = report["frames"][0]
        self.assertEqual(frame["visible_artwork_bbox_px"], {"x_px": 25, "y_px": 15, "width_px": 10, "height_px": 10})
        self.assertEqual(frame["readability_pixels"], 100)
        self.assertAlmostEqual(frame["contrast_actual_composite_to_background"]["median"], 21)
        self.assertEqual(frame["safe_margin"]["violated_sides"], [])
        self.assertEqual(report["summary"]["aesthetic_grade"], None)
        self.assertEqual(report["frames"][0]["human_visual_review"]["status"], "pending")

    def test_local_pixels_find_failure_hidden_by_global_mean(self):
        # The whole frame is almost black, but the actual title falls on white.
        background = Image.new("RGB", (100, 80), "black")
        ImageDraw.Draw(background).rectangle((25, 15, 34, 24), fill="white")
        background.save(self.background)
        frame = self.report()["frames"][0]
        self.assertEqual(frame["contrast_actual_composite_to_background"]["median"], 1)
        self.assertEqual(frame["fraction_below_contrast_1_5"], 1)
        self.assertIn("LOCAL_COMPOSITE_CONTRAST_BELOW_1_5_ON_MORE_THAN_10_PERCENT", frame["flags_for_human_review"])
        self.assertEqual(frame["background_under_readability_pixels"]["palette"][0]["hex"], "#FFFFFF")
        self.assertEqual(frame["palette_roi_px"], {"x_px": 25, "y_px": 15, "width_px": 10, "height_px": 10})

    def test_semitransparent_ink_composite_is_not_opaque_contrast(self):
        request = copy.deepcopy(self.request)
        request["transform"]["opacity"] = 0.2
        frame = self.report(request)["frames"][0]
        self.assertAlmostEqual(frame["contrast_opaque_ink_to_background"]["median"], 21)
        self.assertLess(frame["contrast_actual_composite_to_background"]["median"], 2)
        self.assertEqual(frame["core_pixels"], 0)

    def test_one_pixel_stroke_risk_and_actual_resolution(self):
        artwork = Image.new("RGBA", (20, 20), (255, 255, 255, 0))
        ImageDraw.Draw(artwork).line((3, 10, 16, 10), fill=(255, 255, 255, 255), width=1)
        artwork.save(self.title)
        frame = self.report()["frames"][0]
        self.assertEqual(frame["narrow_feature_check"]["core_pixels_removed_by_square_opening"], 14)
        self.assertEqual(frame["narrow_feature_check"]["fraction_of_core_removed"], 1)
        Image.new("RGB", (100, 80), (250, 250, 250)).save(self.background)
        frame = self.report()["frames"][0]
        self.assertIn("NARROW_FEATURE_LOW_LOCAL_CONTRAST", frame["flags_for_human_review"])

    def test_explicit_protection_and_safe_margin_check_actual_alpha(self):
        request = copy.deepcopy(self.request)
        request["transform"]["x_px"] = 0
        request["protected_rectangles"] = [{"id": "hand", "reason": "synthetic manually protected rectangle", "x_px": 5, "y_px": 15, "width_px": 10, "height_px": 10}]
        frame = self.report(request)["frames"][0]
        self.assertEqual(frame["safe_margin"]["violated_sides"], ["left"])
        self.assertEqual(frame["protected_regions"][0]["visible_overlap_pixels"], 100)
        self.assertEqual(frame["protected_regions"][0]["alpha_weighted_region_coverage_fraction"], 1)
        self.assertFalse(self.report(request)["summary"]["contains_automatic_face_or_subject_detection"])

    def test_clipping_is_measured_before_canvas_crop(self):
        request = copy.deepcopy(self.request)
        request["transform"]["x_px"] = -10
        frame = self.report(request)["frames"][0]
        self.assertAlmostEqual(frame["transform"]["off_canvas_alpha_mass_fraction"], 0.5)
        self.assertIn("ARTWORK_ALPHA_CLIPPED_OUTSIDE_CANVAS", frame["flags_for_human_review"])

    def test_fade_zero_reports_no_visible_pixels_without_nan(self):
        request = copy.deepcopy(self.request)
        request["transform"]["opacity"] = 0
        report = self.report(request)
        frame = report["frames"][0]
        self.assertIsNone(frame["visible_artwork_bbox_px"])
        self.assertIsNone(frame["contrast_actual_composite_to_background"])
        json.dumps(report, allow_nan=False)

    def test_first_middle_last_uses_actual_times_and_per_frame_transform(self):
        request = copy.deepcopy(self.request)
        request["frames"] = [
            {"path": str(self.background), "source_time_s": 4.0, "label": "start", "transform": {"opacity": 0}},
            {"path": str(self.background), "source_time_s": 4.5, "label": "middle"},
            {"path": str(self.background), "source_time_s": 5.0, "label": "end", "transform": {"x_px": 80}},
        ]
        report = self.report(request)
        self.assertEqual([frame["source_time_s"] for frame in report["frames"]], [4.0, 4.5, 5.0])
        self.assertEqual(report["frames"][1]["readability_pixels"], 100)
        self.assertIn("right", report["frames"][2]["safe_margin"]["violated_sides"])

    def test_roi_palette_uses_requested_region_not_whole_frame(self):
        background = Image.new("RGB", (100, 80), "black")
        ImageDraw.Draw(background).rectangle((0, 0, 9, 9), fill=(255, 0, 0))
        background.save(self.background)
        request = copy.deepcopy(self.request)
        request["roi"] = {"x_px": 0, "y_px": 0, "width_px": 10, "height_px": 10}
        colors = self.report(request)["frames"][0]["background_palette"]
        self.assertEqual(colors[0]["hex"], "#FF0000")
        self.assertEqual(colors[0]["area_fraction"], 1)

    def test_real_alpha_required_even_if_rgb_background_looks_black(self):
        Image.new("RGB", (20, 20), "black").save(self.title)
        with self.assertRaisesRegex(ValueError, "real alpha"):
            self.report()

    def test_alpha_border_detects_full_opaque_rectangle(self):
        Image.new("RGBA", (20, 20), "white").save(self.title)
        source_alpha = self.report()["source_alpha"]
        self.assertEqual(source_alpha["transparent_fraction"], 0)
        self.assertEqual(source_alpha["border_visible_fraction_at_alpha_0_05"], 1)

    def test_large_transparent_padding_does_not_trigger_protection_or_margins(self):
        artwork = Image.new("RGBA", (100, 80), (255, 255, 255, 0))
        ImageDraw.Draw(artwork).rectangle((40, 30, 59, 49), fill="white")
        artwork.save(self.title)
        request = copy.deepcopy(self.request)
        request["transform"] = {"x_px": 0, "y_px": 0, "width_px": 100, "height_px": 80}
        request["protected_rectangles"] = [{"x_px": 0, "y_px": 0, "width_px": 20, "height_px": 20}]
        frame = self.report(request)["frames"][0]
        self.assertEqual(frame["visible_artwork_bbox_px"], {"x_px": 40, "y_px": 30, "width_px": 20, "height_px": 20})
        self.assertEqual(frame["safe_margin"]["violated_sides"], [])
        self.assertEqual(frame["protected_regions"][0]["visible_overlap_pixels"], 0)
        self.assertEqual(frame["palette_roi_px"], frame["visible_artwork_bbox_px"])

    def test_near_transparent_fringe_is_omitted_at_default_alpha_32(self):
        artwork = Image.new("RGBA", (20, 20), (255, 255, 255, 1))
        ImageDraw.Draw(artwork).rectangle((5, 5, 14, 14), fill="white")
        artwork.save(self.title)
        frame = self.report()["frames"][0]
        self.assertEqual(frame["visible_artwork_bbox_px"], {"x_px": 25, "y_px": 15, "width_px": 10, "height_px": 10})
        self.assertEqual(frame["readability_pixels"], 100)

    def test_optional_readability_mask_excludes_decoration_but_not_occlusion(self):
        artwork = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
        draw = ImageDraw.Draw(artwork)
        draw.rectangle((0, 0, 9, 9), fill="white")
        draw.rectangle((10, 10, 19, 19), fill=(0, 0, 0, 255))
        artwork.save(self.title)
        mask = Image.new("L", (20, 20), 0)
        ImageDraw.Draw(mask).rectangle((0, 0, 9, 9), fill=255)
        mask_path = self.directory / "glyph-mask.png"
        mask.save(mask_path)
        request = copy.deepcopy(self.request)
        request["readability_mask"] = str(mask_path)
        request["protected_rectangles"] = [{"x_px": 30, "y_px": 20, "width_px": 10, "height_px": 10}]
        frame = self.report(request)["frames"][0]
        self.assertEqual(frame["readability_pixels"], 100)
        self.assertEqual(frame["contrast_actual_composite_to_background"]["median"], 21)
        self.assertEqual(frame["protected_regions"][0]["visible_overlap_pixels"], 100)

    def test_rotation_is_clockwise_about_defined_center(self):
        artwork = Image.new("RGBA", (20, 10), (0, 0, 0, 0))
        ImageDraw.Draw(artwork).rectangle((0, 0, 4, 9), fill="white")
        layer, placement = qa._transform_layer(artwork, {"x_px": 20, "y_px": 20, "width_px": 20, "height_px": 10, "rotation_deg": 90}, (100, 80))
        # Left strip rotates into the top of the expanded rectangle.
        bbox = qa._bbox(np.asarray(layer)[..., 3] >= 128)
        self.assertEqual(placement["rasterized_placement_px"], {"x_px": 25, "y_px": 15, "width_px": 10, "height_px": 20})
        self.assertEqual(bbox, (25, 15, 35, 20))

    def test_dimensions_and_unbounded_parameters_are_not_guessed(self):
        request = copy.deepcopy(self.request)
        request["canvas"]["width_px"] = 101
        with self.assertRaisesRegex(ValueError, "differ from canvas"):
            self.report(request)
        request = copy.deepcopy(self.request)
        request["transform"]["opacity"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            self.report(request)
        request = copy.deepcopy(self.request)
        request["roi"] = {"x_px": 95, "y_px": 0, "width_px": 10, "height_px": 10}
        with self.assertRaisesRegex(ValueError, "wholly inside"):
            self.report(request)

    def test_transfer_declaration_is_explicit_and_hdr_not_guessed(self):
        self.assertAlmostEqual(float(qa._luminance(np.array([128, 128, 128]), "srgb")), 0.2158605, places=6)
        self.assertAlmostEqual(float(qa._luminance(np.array([128, 128, 128]), "bt709")), 0.2614815, places=6)
        request = copy.deepcopy(self.request)
        request["rgb_transfer"] = "bt709"
        report = self.report(request)
        self.assertEqual(report["rgb_transfer"]["declaration"], "bt709")
        self.assertFalse(report["rgb_transfer"]["color_conversion_performed"])
        request["rgb_transfer"] = "unknown"
        with self.assertRaisesRegex(ValueError, "rgb_transfer"):
            self.report(request)

    def test_cli_preserves_sources_and_refuses_existing_outputs(self):
        before = {path: qa._sha256(path) for path in (self.title, self.background)}
        request_path = self.directory / "request.json"
        request_path.write_text(json.dumps(self.request), encoding="utf-8")
        output = self.directory / "report.json"
        previews = self.directory / "previews"
        command = [sys.executable, str(MODULE_PATH), "--request", str(request_path), "--output", str(output), "--preview-dir", str(previews)]
        first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((previews / "frame-001-composite.png").exists())
        second = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("must be new", second.stderr)
        self.assertEqual(before, {path: qa._sha256(path) for path in before})


if __name__ == "__main__":
    unittest.main()

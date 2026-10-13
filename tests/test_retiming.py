"""Continuous output-time ramps: analytic samples and actual FFmpeg timestamps.

The optional FFmpeg check preserves synthetic frame identity while testing
the inverse in the real expression evaluator, including decreasing and flat
segments. It does not certify motion interpolation or editor preset parity.
"""
import hashlib
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.retiming import (output_time, setpts_expression, source_span,
                                source_time, validate_curve)


def curve(*pairs):
    return [{'time': time, 'speed': speed} for time, speed in pairs]


class RetimingTests(unittest.TestCase):
    def test_constant_speed_source_and_output_units(self):
        knots = curve((0, 2), (3, 2))
        self.assertEqual(source_span(knots), 6)
        self.assertEqual(source_time(knots, 1.25), 2.5)
        self.assertEqual(output_time(knots, 2.5), 1.25)
        self.assertEqual(source_time(knots, 3), 6)
        self.assertEqual(output_time(knots, 6), 3)

    def test_known_linear_ramp_integral_and_inverse(self):
        knots = curve((0, .5), (1, 1.5), (2, .5))
        # First half: integral(.5+t) = .5*t + .5*t**2.
        self.assertEqual(source_time(knots, .5), .375)
        self.assertEqual(source_time(knots, 1), 1)
        self.assertEqual(source_time(knots, 1.5), 1.625)
        self.assertEqual(source_span(knots), 2)
        self.assertAlmostEqual(output_time(knots, .375), .5, places=14)
        self.assertAlmostEqual(output_time(knots, 1.625), 1.5, places=14)

    def test_extreme_decreasing_ramp_is_monotonic_and_continuous(self):
        knots = curve((0, 10), (1, .1), (2, .1), (3, 10))
        previous = -1
        for index in range(1201):
            time = index / 400
            source = source_time(knots, time)
            self.assertGreater(source, previous)
            self.assertAlmostEqual(output_time(knots, source), time, places=12)
            previous = source
        for time in (1, 2):
            left = source_time(knots, time - 1e-8)
            right = source_time(knots, time + 1e-8)
            self.assertLess(right-left, 3e-8)

    def test_seeded_nonuniform_roundtrips_and_tiny_speed_change(self):
        rng = random.Random(37402)
        for _ in range(20):
            times = [0] + sorted(rng.uniform(.001, 3.999) for _ in range(8)) + [4]
            knots = curve(*[(time, rng.uniform(.1, 10)) for time in times])
            validate_curve(knots, 4, 25)
            span = source_span(knots)
            for _ in range(30):
                source = rng.uniform(0, span)
                output = output_time(knots, source)
                self.assertAlmostEqual(source_time(knots, output), source, delta=2e-12)
        knots = curve((0, 1), (2, 1 + 1e-14))
        self.assertAlmostEqual(output_time(knots, 1), 1, places=13)

    def test_frame_endpoints_and_subframe_interior_knots(self):
        knots = curve((0, .1), (.123, 1), (2, 10))
        normalized = validate_curve(knots, 2, 25)
        self.assertEqual(normalized, knots)
        self.assertIsNot(normalized, knots)
        normalized[0]['speed'] = 2
        self.assertEqual(knots[0]['speed'], .1)
        ntsc_duration = 60 * 1001/30000
        validate_curve(curve((0, 1), (ntsc_duration, 1)), ntsc_duration, 30000/1001)
        for duration in (2.001, 1e-12):
            with self.assertRaises(ValueError):
                validate_curve(curve((0, 1), (duration, 1)), duration, 25)

    def test_rejects_malformed_curves_and_bad_domains(self):
        valid = curve((0, 1), (1, 2))
        invalid = [None, [], {}, 'curve', [{'time': 0, 'speed': 1}],
                   curve((.1, 1), (1, 1)), curve((0, 1), (0, 2)),
                   curve((0, 1), (-1, 2)), curve((0, 0), (1, 1)),
                   curve((0, 1), (1, 10.01)), curve((0, True), (1, 1)),
                   curve((0, 1), (float('inf'), 1)),
                   curve((0, 1), (1, float('nan'))),
                   [{'time': 0, 'speed': 1, 'extra': 2}, valid[1]],
                   [{'time': '0', 'speed': 1}, valid[1]]]
        for knots in invalid:
            with self.subTest(knots=knots), self.assertRaises(ValueError):
                source_span(knots)
        for duration, fps in [(0, 25), (1, 0), (True, 25), (1, False),
                              (float('nan'), 25), (1, float('inf')), (2, 25)]:
            with self.subTest(duration=duration, fps=fps), self.assertRaises(ValueError):
                validate_curve(valid, duration, fps)
        for value in (-.001, 1.001, float('nan'), True):
            with self.assertRaises(ValueError): source_time(valid, value)
        for value in (-.001, 1.501, float('inf'), False):
            with self.assertRaises(ValueError): output_time(valid, value)
        self.assertEqual(output_time(valid, math.nextafter(1.5, math.inf)), 1)
        self.assertEqual(source_time(valid, math.nextafter(1., math.inf)), 1.5)
        for variable in (None, '', ' '):
            with self.assertRaises(ValueError): setpts_expression(valid, variable)

    @unittest.skipUnless(os.environ.get('VIDEO_EDIT_FFMPEG'), 'Set VIDEO_EDIT_FFMPEG for real time-map check')
    def test_real_ffmpeg_preserves_frame_identity_and_analytic_timestamps(self):
        ffmpeg = os.environ['VIDEO_EDIT_FFMPEG']
        knots = curve((0, .5), (.5, 2), (1, 2), (2, .5))
        validate_curve(knots, 2, 40)
        fps = 40
        count = round(source_span(knots) * fps)
        frames = [bytes([n, 255-n, (n*3)%256]) * (8*8) for n in range(count)]
        expression = setpts_expression(knots)
        result = subprocess.run([ffmpeg, '-v', 'error', '-threads', '1',
            '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '8x8',
            '-framerate', str(fps), '-i', 'pipe:0', '-vf', f"settb=AVTB,setpts='{expression}'",
            '-an', '-c:v', 'rawvideo', '-pix_fmt', 'rgb24', '-threads', '1',
            '-fps_mode', 'passthrough', '-enc_time_base', '1/1000000',
            '-f', 'framemd5', 'pipe:1'], input=b''.join(frames), capture_output=True,
            timeout=60, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        lines = result.stdout.decode().splitlines()
        tb = next(line for line in lines if line.startswith('#tb 0:'))
        match = re.search(r'(\d+)/(\d+)', tb)
        time_base = int(match[1])/int(match[2])
        output = [line.split(',') for line in lines if line and not line.startswith('#')]
        self.assertEqual(len(output), count)
        for index, (record, frame) in enumerate(zip(output, frames)):
            self.assertEqual(record[-1].strip(), hashlib.md5(frame).hexdigest())
            actual = int(record[2]) * time_base
            self.assertAlmostEqual(actual, output_time(knots, index/fps), delta=2.1e-6)


if __name__ == '__main__':
    unittest.main()

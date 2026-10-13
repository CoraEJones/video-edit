"""Safety and provenance checks for the public-video corpus downloader."""
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_benchmark as benchmark


class BenchmarkFetchTests(unittest.TestCase):
    def test_ambiguous_and_restricted_licenses_are_rejected(self):
        for name in ("", "Copyrighted free use", "CC BY-NC 4.0", "CC BY-ND 4.0", "GFDL", "CC BY-SA 4.0, GFDL"):
            self.assertIsNone(benchmark.accepted_license({"LicenseShortName": {"value": name}}))
        self.assertEqual(benchmark.accepted_license({"LicenseShortName": {"value": "Public domain"}})["license"], "Public domain")
        self.assertIsNotNone(benchmark.accepted_license({"LicenseShortName": {"value": "CC BY-SA 4.0"},
                                                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}))

    def test_variant_rejects_oversized_and_out_of_duration(self):
        info = {"duration": 10, "mediatype": "VIDEO", "width": 1920, "height": 1080, "size": 99_000_000,
                "derivatives": [{"src": "https://upload.wikimedia.org/test.480p.webm", "type": "video/webm", "width": 854,
                                 "height": 480, "bandwidth": 500_000, "transcodekey": "480p.vp9.webm"}]}
        self.assertEqual(benchmark.choose_variant(info)["download_variant"], "480p.vp9.webm")
        self.assertIsNone(benchmark.choose_variant(dict(info, duration=91)))
        self.assertIsNone(benchmark.choose_variant(info, max_bytes=1))

    def test_portable_manifest_path_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                benchmark.safe_relative(Path(directory), "../outside.webm")
            self.assertTrue(benchmark.safe_relative(Path(directory), "media/test.webm").is_relative_to(Path(directory).resolve()))

    def test_topic_round_robin_and_named_part_deduplication(self):
        rows = [{"group": "animals", "discovery_query": query, "title": title}
                for query, title in (("bird", "File:Bird A.webm"), ("bird", "File:Bird B.webm"),
                                     ("dog", "File:Dog A.webm"), ("cat", "File:Cat A.webm"))]
        self.assertEqual([row["discovery_query"] for row in benchmark.balanced_pool(rows, "animals")],
                         ["bird", "dog", "cat", "bird"])
        self.assertEqual(benchmark.source_work_key({"title": "File:Cooking Boodog - 1.webm"}),
                         benchmark.source_work_key({"title": "File:Cooking Boodog - 3.webm"}))
        self.assertEqual(benchmark.source_work_key({"title": "File:Global snow (SVS4995 - north 2160p30).webm"}),
                         benchmark.source_work_key({"title": "File:Global snow (SVS4995 - south 1080p30).webm"}))
        self.assertFalse(benchmark.fits_discovery_group({"group": "nature_landscape", "title": "File:Gravity Waves (CIRA 2024).webm"}))

    def test_corrupt_existing_manifest_is_not_silently_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            benchmark.write_json(root / "manifest.json", [{"id": "commons-1", "relative_path": "media/missing.webm", "bytes": 10, "sha256": "wrong"}])
            with self.assertRaisesRegex(ValueError, "missing or corrupt"):
                benchmark.download_corpus(root, [], 25, "ffprobe", "ffmpeg", 1000, 10000)

    def test_incomplete_download_is_not_published(self):
        class Response(io.BytesIO):
            headers = {"Content-Length": "100"}
        row = {"id": "commons-1", "group": "animals", "download_url": "https://upload.wikimedia.org/test.webm"}
        with tempfile.TemporaryDirectory() as directory, patch.object(benchmark, "urlopen", side_effect=lambda *a, **k: Response(b"short")), \
                patch.object(benchmark.time, "sleep"), patch.object(benchmark, "probe_and_decode") as probe:
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                benchmark.download_one(Path(directory), row, "ffprobe", "ffmpeg", 1000)
            self.assertFalse(list(Path(directory).rglob("*.webm")))
            self.assertFalse(list(Path(directory).rglob("*.part")))
            self.assertFalse(probe.called)

    def test_decoder_error_log_is_rejected_even_with_zero_exit(self):
        probe = {"streams": [{"codec_type": "video"}, {"codec_type": "audio"}], "format": {"duration": "8"}}
        outputs = [types.SimpleNamespace(stdout=json.dumps(probe)),
                   types.SimpleNamespace(returncode=0, stderr="audio decode failed")]
        with patch.object(benchmark.subprocess, "run", side_effect=outputs):
            with self.assertRaisesRegex(ValueError, "Full decode failed"):
                benchmark.probe_and_decode(Path("fixture.webm"), "ffprobe", "ffmpeg")

    def test_resume_uses_hash_and_avoids_network(self):
        row = {"id": "commons-1", "group": "animals", "download_url": "https://upload.wikimedia.org/test.webm"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "media/animals/commons-1.webm"; media.parent.mkdir(parents=True); media.write_bytes(b"verified fixture")
            previous = dict(row, bytes=media.stat().st_size, sha256=benchmark.hash_file(media))
            benchmark.write_json(root / "items/commons-1.json", previous)
            with patch.object(benchmark, "urlopen") as network:
                self.assertEqual(benchmark.download_one(root, row, "ffprobe", "ffmpeg", 1000), previous)
                with self.assertRaisesRegex(ValueError, "differ from pinned"):
                    benchmark.download_one(root, dict(row, sha256="different-pinned-source"), "ffprobe", "ffmpeg", 1000)
                self.assertFalse(network.called)

    def test_pinned_source_change_is_not_published(self):
        class Response(io.BytesIO):
            headers = {"Content-Length": "5"}
        row = {"id": "commons-1", "group": "animals", "download_url": "https://upload.wikimedia.org/test.webm", "sha256": "old-source-hash"}
        with tempfile.TemporaryDirectory() as directory, patch.object(benchmark, "urlopen", side_effect=lambda *a, **k: Response(b"newer")), \
                patch.object(benchmark.time, "sleep"), patch.object(benchmark, "probe_and_decode", return_value={}):
            with self.assertRaisesRegex(ValueError, "source bytes changed"):
                benchmark.download_one(Path(directory), row, "ffprobe", "ffmpeg", 1000)
            self.assertFalse(list(Path(directory).rglob("*.webm")))


if __name__ == "__main__":
    unittest.main()

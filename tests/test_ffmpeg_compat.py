"""Choose file-backed graphs without relying on removed FFmpeg CLI aliases."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit import common


class FilterScriptCompatibilityTests(unittest.TestCase):
    def setUp(self):
        common._filter_script_option.cache_clear()
        self.addCleanup(common._filter_script_option.cache_clear)

    def test_release_versions_choose_modern_or_legacy_file_option(self):
        for version, expected in [('6.1.4', '-filter_complex_script'),
                                  ('n7.0', '-/filter_complex'),
                                  ('9.0.2-full_build', '-/filter_complex')]:
            with self.subTest(version=version), patch.object(common, 'run', return_value=SimpleNamespace(stdout=f'ffmpeg version {version}\n'.encode())):
                common._filter_script_option.cache_clear()
                self.assertEqual(common.filter_script_args('ffmpeg', Path('many layers.txt')), [expected, 'many layers.txt'])

    def test_git_build_uses_library_version(self):
        with patch.object(common, 'run', return_value=SimpleNamespace(stdout=b'ffmpeg version N-123456-git\nlibavutil     60. 14.100 / 60. 14.100\n')):
            self.assertEqual(common.filter_script_args('ffmpeg', 'graph.txt')[0], '-/filter_complex')

    def test_probe_is_cached_per_binary(self):
        with patch.object(common, 'run', return_value=SimpleNamespace(stdout=b'ffmpeg version 9.0.2\n')) as probe:
            common.filter_script_args('ffmpeg-a', 'a.txt')
            common.filter_script_args('ffmpeg-a', 'b.txt')
            common.filter_script_args('ffmpeg-b', 'c.txt')
            self.assertEqual(probe.call_count, 2)

    def test_unknown_banner_fails_explicitly(self):
        with patch.object(common, 'run', return_value=SimpleNamespace(stdout=b'unknown vendor banner')):
            with self.assertRaises(common.EditError) as caught:
                common.filter_script_args('ffmpeg', 'graph.txt')
            self.assertEqual(caught.exception.code, 'FFMPEG_VERSION_UNKNOWN')


if __name__ == '__main__': unittest.main()

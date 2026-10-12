"""Confirmed user preferences must also be respected by the editing plan."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.plan import validate


class PlanPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root / 'photo.jpg'
        source.write_bytes(b'fixture: media probing is disabled in this validation test')
        self.plan = {
            'schema_version': '1.0', 'width': 640, 'height': 360, 'fps': 30, 'duration': 2,
            'request': {'voiceover': False, 'subtitles': False, 'title_mode': 'fonts_only'},
            'review': {'status': 'reviewed', 'evidence': ['Synthetic validation fixture only']},
            'inventory': [{'id': 'p', 'kind': 'image', 'absolute_path': str(source),
                           'duration': 5, 'width': 640, 'height': 360, 'fps': 0, 'has_audio': False}],
            'shots': [{'id': 'p', 'index': 1, 'start': 0, 'source_in': 0, 'duration': 2, 'speed': 1}],
        }

    def result(self):
        return validate(self.plan, self.root / 'plan.json', {}, inspect_files=False)

    def test_no_voice_no_captions_and_font_titles_are_valid(self):
        self.plan['titles'] = [{'text': '回忆', 'start': 0, 'end': 2}]
        self.assertTrue(self.result()['valid'], self.result())

    def test_disabled_voice_cannot_be_added_to_plan(self):
        self.plan['narration'] = [{'text': '未经请求的旁白', 'start': 0, 'end': 2}]
        self.assertIn('NARRATION_DISABLED', [e['code'] for e in self.result()['errors']])

    def test_font_only_rejects_declared_art_title(self):
        self.plan['techniques'] = ['art_title_overlay']
        self.assertIn('ART_TITLE_DISABLED', [e['code'] for e in self.result()['errors']])


if __name__ == '__main__':
    unittest.main()

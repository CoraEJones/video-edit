import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.intake import DEFAULTS, confirm_request, inspect_request, summary_lines


class EditorialRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name); media = root / 'media'; media.mkdir()
        (media / 'fixture.png').write_bytes(b'Synthetic request-check fixture only.')
        self.request = dict(DEFAULTS, media_dir=str(media), output_dir=str(root / 'out'))

    def test_optional_editorial_fields_are_visible_and_bound_to_confirmation(self):
        request = dict(self.request, audience='家人', viewing_context='电视', color_preference='自然通透 70%',
                       must_keep_ranges=[{'asset_id': 'v1', 'source_start': 2, 'source_end': 4}])
        confirmed = confirm_request(request, True)
        self.assertTrue(inspect_request(confirmed)['ready'])
        text = '\n'.join(summary_lines(confirmed))
        self.assertIn('家人', text); self.assertIn('source_start', text)
        changed = copy.deepcopy(confirmed); changed['must_keep_ranges'][0]['source_end'] = 5
        self.assertFalse(inspect_request(changed)['ready'])

    def test_invalid_ranges_and_types_are_rejected(self):
        for value in ('v1', [{}], [{'asset_id': 'v1', 'source_start': 3, 'source_end': 2}],
                      [{'asset_id': 'v1', 'source_start': False, 'source_end': 1}]):
            self.assertTrue(inspect_request(dict(self.request, must_keep_ranges=value))['invalid_fields'])
        self.assertTrue(inspect_request(dict(self.request, audience=[]))['invalid_fields'])


if __name__ == '__main__': unittest.main()

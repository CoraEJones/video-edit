"""Mode decisions run without installing software or launching desktop windows."""
import copy
import importlib.metadata
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from video_edit import environment as env


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name in ('ffmpeg', 'ffprobe', 'font.ttf'):
            (root/name).write_bytes(b'test fixture, not an executable')
        self.cfg = {'ffmpeg': str(root/'ffmpeg'), 'ffprobe': str(root/'ffprobe'),
                    'font_path': str(root/'font.ttf'), 'jianying_install_dir': None,
                    'delivery_mode': 'mp4', 'entry_mode': 'chat', 'host': 'codex'}
        self.modules = {'numpy': True, 'PIL': True, 'fontTools': True, 'tkinter': False,
                        'pyJianYingDraft': False, 'faster_whisper': False}

    def check(self, cfg=None, **kwargs):
        with patch.object(env, 'dependency_state', return_value=(self.modules, [], {})), \
             patch.object(env, 'application_state', return_value={'ready': True, 'selected_host': 'codex'}), \
             patch.object(env, 'model_path', return_value=None), \
             patch.object(env.importlib.metadata, 'version', side_effect=importlib.metadata.PackageNotFoundError), \
             patch('video_edit.typography.fonts', return_value={}), \
             patch.object(env, 'run', side_effect=AssertionError('no desktop or optional process in chat')):
            return env.doctor(cfg or self.cfg, **kwargs)

    def test_codex_chat_mp4_without_jianying_tk_model_is_ready(self):
        result = self.check()
        self.assertTrue(result['ready'], result['problems'])
        self.assertFalse(result['capabilities']['graphical_wizard_checked'])
        self.assertFalse(result['capabilities']['native_editable_draft'])
        self.assertIsNone(result['rectangle_mask_dir'])
        self.assertIn('unknown', result['capabilities']['host_vision'])

    def test_deepseek_only_is_equally_supported(self):
        self.assertTrue(self.check(host='deepseek')['ready'])
        self.assertEqual(self.check(host='deepseek')['host'], 'deepseek')

    def test_editable_requires_editor(self):
        result = self.check(delivery_mode='editable')
        self.assertFalse(result['ready'])
        self.assertTrue(any('可编辑工程' in p for p in result['problems']))

    def test_transcription_is_required_only_when_requested(self):
        cfg = dict(self.cfg, transcription_required=True)
        result = self.check(cfg)
        self.assertFalse(result['ready'])
        self.assertTrue(any('语音识别' in p for p in result['problems']))

    def test_voiceover_is_required_only_when_requested(self):
        cfg = dict(self.cfg, voiceover_required=True)
        result = self.check(cfg)
        self.assertFalse(result['ready'])
        self.assertTrue(any('配音' in p for p in result['problems']))

    def test_missing_base_dependency_blocks(self):
        with patch.object(env.importlib.util, 'find_spec', return_value=None):
            _, missing, _ = env.dependency_state(self.cfg)
        self.assertEqual(missing, ['numpy', 'PIL', 'fontTools'])

    def test_wizard_and_editable_add_only_their_dependencies(self):
        cfg = dict(self.cfg, entry_mode='wizard', delivery_mode='editable', transcription_required=True)
        with patch.object(env.importlib.util, 'find_spec', return_value=None):
            _, missing, _ = env.dependency_state(cfg)
        self.assertEqual(set(missing), {'numpy', 'PIL', 'fontTools', 'tkinter', 'pyJianYingDraft', 'faster_whisper'})

    def test_graphical_failure_does_not_block_chat_but_blocks_wizard(self):
        self.modules['tkinter'] = True
        result = self.check(entry_mode='wizard')
        self.assertFalse(result['ready'])
        self.assertTrue(any('本地窗口' in p for p in result['problems']))
        self.assertTrue(self.check(entry_mode='chat')['ready'])

    def test_invalid_selection_rejected_without_mutating_configuration(self):
        original = copy.deepcopy(self.cfg)
        with self.assertRaises(env.EditError): self.check(delivery_mode='maybe')
        self.assertEqual(original, self.cfg)


if __name__ == '__main__': unittest.main()

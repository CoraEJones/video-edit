"""Request intake contract; synthetic files only, no video rendering or GUI use."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from video_edit.common import EditError
from video_edit.intake import (DEFAULTS, confirm_request, inspect_request,
                               require_confirmed_request, require_delivery_request,
                               summary_lines)


class _Variable:
    def __init__(self, value=None): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class _Widget:
    def __init__(self, parent=None, **kwargs):
        self.children = []; self.options = kwargs
        if parent is not None: parent.children.append(self)
    def pack(self, **kwargs): pass
    def pack_forget(self): pass
    def configure(self, **kwargs): self.options.update(kwargs)
    config = configure
    def bind(self, *args, **kwargs): pass
    def destroy(self): pass
    def winfo_children(self): return self.children
    def yview(self, *args): pass
    def yview_moveto(self, *args): pass
    def create_window(self, *args, **kwargs): return 1
    def set(self, *args): pass


def _wizard_tk(cancel_at_summary=False):
    """Widget double exercising real wizard navigation and confirmation callbacks."""
    class Root(_Widget):
        def withdraw(self): pass
        def title(self, *args): pass
        def geometry(self, *args): pass
        def minsize(self, *args): pass
        def protocol(self, *args): pass
        def deiconify(self): pass
        def lift(self): pass
        def mainloop(self):
            def descendants(widget):
                for child in widget.children:
                    yield child
                    yield from descendants(child)
            controls = list(descendants(self))
            next_button = next(w for w in controls if w.options.get('text') == '下一步 →')
            for _ in range(8): next_button.options['command']()
            if cancel_at_summary:
                next(w for w in controls if w.options.get('text') == '取消').options['command']()
            else:
                next_button.options['command']()
    fake = types.ModuleType('tkinter')
    fake.Tk = Root; fake.TclError = RuntimeError; fake.Canvas = _Widget
    fake.IntVar = fake.StringVar = fake.BooleanVar = _Variable
    fake.ttk = types.SimpleNamespace(**{name: _Widget for name in
                                       ('Frame', 'Label', 'Scrollbar', 'Entry', 'Combobox', 'Checkbutton', 'Button')})
    fake.ttk.Style = lambda root: Mock()
    fake.messagebox = Mock(); fake.filedialog = Mock()
    return fake


class RequestTests(unittest.TestCase):
    def setUp(self):
        # Every path is synthetic and isolated; no project files are touched.
        self.temporary = tempfile.TemporaryDirectory(prefix='video-edit-request-test-')
        self.root = Path(self.temporary.name)
        self.media = self.root / '素材'
        self.media.mkdir()
        (self.media / 'clip.mp4').write_bytes(b'synthetic readability fixture, not real video')
        self.request = deepcopy(DEFAULTS)
        self.request.update(media_dir=str(self.media), output_dir=str(self.root / '新作品'))

    def tearDown(self):
        self.temporary.cleanup()

    def test_no_prompt_fields_means_questions_and_no_guessed_source(self):
        request = {}
        check = inspect_request(request)
        self.assertIn('media_dir', check['missing_fields'])
        self.assertIn('output_dir', check['missing_fields'])
        self.assertIn('delivery_mode', check['missing_fields'])
        self.assertIsNone(check['suggested_output_dir'])
        self.assertTrue(check['confirmation_required'])
        self.assertFalse(check['processing_started'])
        self.assertEqual(request, {})

    def test_missing_output_is_suggested_not_filled_or_confirmed(self):
        request = {'media_dir': str(self.media), 'rhythm': '轻快活泼'}
        check = inspect_request(request)
        self.assertNotIn('media_dir', check['missing_fields'])
        self.assertNotIn('rhythm', check['missing_fields'])
        self.assertIn('output_dir', check['missing_fields'])
        self.assertTrue(check['suggested_output_dir'])
        self.assertNotIn('output_dir', request)
        self.assertFalse(Path(check['suggested_output_dir']).exists())

    def test_nonexistent_and_example_source_cannot_be_confirmed(self):
        for value in (str(self.root / 'missing'), '<素材目录>', '${MEDIA}'):
            with self.subTest(value=value):
                request = dict(self.request, media_dir=value)
                check = inspect_request(request)
                self.assertTrue(any(p['field'] == 'media_dir' for p in check['invalid_paths']))
                with self.assertRaises(EditError) as caught:
                    confirm_request(request, True)
                self.assertEqual(caught.exception.code, 'REQUEST_INCOMPLETE')

    def test_example_output_and_output_file_are_rejected(self):
        for value in ('<输出目录>', str(self.media / 'clip.mp4')):
            with self.subTest(value=value):
                check = inspect_request(dict(self.request, output_dir=value))
                self.assertTrue(any(p['field'] == 'output_dir' for p in check['invalid_paths']))

    def test_an_existing_example_named_directory_is_a_real_source(self):
        from video_edit.intake import _path_issue
        # Map the example drive to a real isolated directory, without touching D:.
        with patch('video_edit.intake.Path', return_value=self.media):
            self.assertIsNone(_path_issue('media_dir', r'D:\旅行素材', kind='directory', must_exist=True))

    def test_request_dependency_config_does_not_infer_asr_from_subtitles(self):
        from video_edit.cli import request_config
        cfg = request_config({}, {'delivery_mode': 'mp4', 'subtitles': True, 'voiceover': False})
        self.assertEqual(cfg, {'delivery_mode': 'mp4', 'voiceover_required': False})
        request_config(cfg, {'transcription_required': True, 'voiceover': True})
        self.assertTrue(cfg['transcription_required'])
        self.assertTrue(cfg['voiceover_required'])

    def test_malformed_paths_report_invalid_instead_of_crashing(self):
        check = inspect_request(dict(self.request, output_dir=42, must_keep_files=[None, {'bad': 'path'}]))
        fields = {p['field'] for p in check['invalid_paths']}
        self.assertEqual(fields, {'output_dir', 'must_keep_files[0]', 'must_keep_files[1]'})

    def test_empty_source_or_output_equal_to_source_are_rejected(self):
        empty = self.root / 'empty'; empty.mkdir()
        self.assertFalse(inspect_request(dict(self.request, media_dir=str(empty)))['complete'])
        self.assertFalse(inspect_request(dict(self.request, output_dir=str(self.media)))['complete'])

    def test_output_inside_source_is_rejected_before_it_can_be_rescanned(self):
        request = dict(self.request, output_dir=str(self.media / '成片'))
        check = inspect_request(request)
        self.assertFalse(check['complete'])
        self.assertTrue(any(p['field'] == 'output_dir' for p in check['invalid_paths']))
        with self.assertRaises(EditError) as caught:
            confirm_request(request, True)
        self.assertEqual(caught.exception.code, 'REQUEST_INCOMPLETE')
        self.assertFalse((self.media / '成片').exists())

    def test_output_parent_of_source_can_hold_a_separate_work_subdirectory(self):
        # Exporters create a new named work directory under this parent.
        check = inspect_request(dict(self.request, output_dir=str(self.root)))
        self.assertTrue(check['complete'])

    def test_new_output_directory_is_allowed_but_not_created_by_check(self):
        check = inspect_request(self.request)
        self.assertTrue(check['complete'])
        self.assertFalse(check['ready'])
        self.assertFalse(Path(self.request['output_dir']).exists())

    def test_confirmation_requires_real_bool_true_and_does_not_mutate_input(self):
        for answer in (False, None, '', 'yes', 1):
            self.assertNotIn('confirmation', confirm_request(self.request, answer))
        confirmed = confirm_request(self.request, True)
        self.assertNotIn('confirmation', self.request)
        self.assertTrue(inspect_request(confirmed)['ready'])
        self.assertEqual(confirmed['confirmation']['method'], 'chat_explicit_reply')

    def test_change_style_subtitle_path_or_mode_invalidates_confirmation(self):
        confirmed = confirm_request(self.request, True)
        for key, value in (
                ('rhythm', '轻快活泼'), ('subtitles', False), ('delivery_mode', 'editable'),
                ('output_dir', str(self.root / 'changed')), ('title_mode', 'fonts_only'),
                ('target_seconds', 120), ('audio_policy', 'mute_all')):
            with self.subTest(key=key):
                changed = deepcopy(confirmed); changed[key] = value
                check = inspect_request(changed)
                self.assertTrue(check['confirmation_required'])
                with self.assertRaises(EditError) as caught:
                    require_confirmed_request(changed)
                self.assertEqual(caught.exception.code, 'REQUEST_CONFIRMATION_REQUIRED')

    def test_processing_metadata_does_not_invalidate_confirmation(self):
        confirmed = confirm_request(self.request, True)
        confirmed.update(inventory_path='internal.json', analysis_dir='internal', host='codex', _cached=True)
        self.assertTrue(inspect_request(confirmed)['ready'])

    def test_voiceoff_subtitlesoff_auto_music_skip_conditional_questions(self):
        request = dict(self.request, voiceover=False, subtitles=False, music='自动配乐')
        for key in ('voice_gender', 'subtitle_language', 'music_file'):
            request.pop(key)
        self.assertTrue(inspect_request(request)['complete'])
        request.update(voiceover=True, subtitles=True, music='使用我自己的音乐')
        check = inspect_request(request)
        self.assertEqual(set(check['missing_fields']), {'voice_gender', 'subtitle_language', 'music_file'})

    def test_chosen_music_and_must_keep_files_must_exist(self):
        request = dict(self.request, music='使用我自己的音乐', music_file=str(self.root / 'gone.mp3'),
                       must_keep_files=[str(self.root / 'gone.mp4')])
        fields = {p['field'] for p in inspect_request(request)['invalid_paths']}
        self.assertEqual(fields, {'music_file', 'must_keep_files[0]'})

    def test_must_keep_outside_media_scope_is_not_silently_ignored(self):
        elsewhere = self.root / 'elsewhere.mp4'; elsewhere.write_bytes(b'synthetic')
        check = inspect_request(dict(self.request, must_keep_files=[str(elsewhere)]))
        self.assertEqual(check['invalid_paths'][0]['field'], 'must_keep_files[0]')

    def test_conflicting_audio_choices_require_follow_up(self):
        check = inspect_request(dict(self.request, music='只保留原声', audio_policy='mute_all'))
        self.assertEqual(check['invalid_fields'][0]['field'], 'audio_policy')
        self.assertTrue(check['confirmation_required'])

    def test_delegate_and_empty_optional_story_answers_are_explicit_answers(self):
        request = dict(self.request, target_seconds=None, theme='由助手推荐', rhythm='由助手推荐',
                       context='', must_keep='', must_keep_files=[])
        confirmed = confirm_request(request, True)
        self.assertTrue(inspect_request(confirmed)['ready'])
        summary = '\n'.join(summary_lines(confirmed))
        self.assertIn('目标时长：由助手推荐', summary)
        self.assertIn('人物与故事背景：暂无补充', summary)
        self.assertIn('无需剪映', summary)

    def test_legacy_complete_request_without_confirmation_cannot_execute(self):
        request = dict(self.request, schema_version='1.0')
        with self.assertRaises(EditError) as caught:
            require_confirmed_request(request)
        self.assertEqual(caught.exception.code, 'REQUEST_CONFIRMATION_REQUIRED')

    def test_cancel_clears_previous_confirmation_and_never_starts(self):
        confirmed = confirm_request(self.request, True)
        cancelled = confirm_request(confirmed, False)
        self.assertNotIn('confirmation', cancelled)
        check = inspect_request(cancelled)
        self.assertFalse(check['ready'])
        self.assertFalse(check['processing_started'])

    def test_folder_picker_cancel_returns_none_without_creating_output(self):
        from video_edit.wizard import show
        root = Mock()
        fake = types.ModuleType('tkinter')
        fake.Tk = Mock(return_value=root)
        fake.TclError = RuntimeError
        fake.ttk = Mock()
        fake.messagebox = Mock()
        fake.filedialog = Mock()
        fake.filedialog.askdirectory.return_value = ''
        with patch.dict(sys.modules, {'tkinter': fake}):
            self.assertIsNone(show({'output_root': str(self.root / '未创建')}))
        root.destroy.assert_called_once()
        self.assertFalse((self.root / '未创建').exists())

    def test_wizard_prefills_answers_and_confirms_visible_recommendations(self):
        from video_edit.wizard import show
        fake = _wizard_tk()
        # Partial answer leaves defaults as visible proposals until the final button.
        supplied = {'media_dir': str(self.media), 'output_dir': str(self.root / 'wizard-output'),
                    'target_seconds': 123, 'rhythm': '轻快活泼', 'voiceover': False, 'subtitles': False}
        with patch.dict(sys.modules, {'tkinter': fake}):
            confirmed = show({'delivery_mode': 'editable'}, supplied)
        fake.filedialog.askdirectory.assert_not_called()
        fake.messagebox.showinfo.assert_not_called()
        self.assertEqual(confirmed['target_seconds'], 123)
        self.assertEqual(confirmed['rhythm'], supplied['rhythm'])
        self.assertEqual(confirmed['delivery_mode'], 'editable')
        self.assertTrue(inspect_request(confirmed)['ready'])
        self.assertEqual(confirmed['confirmation']['method'], 'wizard_confirm_button')
        self.assertFalse(Path(confirmed['output_dir']).exists())

    def test_wizard_cancel_at_final_summary_does_not_confirm(self):
        from video_edit.wizard import show
        fake = _wizard_tk(cancel_at_summary=True)
        with patch.dict(sys.modules, {'tkinter': fake}):
            self.assertIsNone(show({}, self.request))
        self.assertFalse(Path(self.request['output_dir']).exists())

    def test_delivery_output_and_type_must_match_confirmation(self):
        confirmed = confirm_request(self.request, True)
        self.assertTrue(require_delivery_request(confirmed, self.request['output_dir'], 'mp4')['ready'])
        for out, mode in ((self.root / 'elsewhere', 'mp4'), (self.request['output_dir'], 'editable')):
            with self.subTest(out=out, mode=mode), self.assertRaises(EditError) as caught:
                require_delivery_request(confirmed, out, mode)
            self.assertEqual(caught.exception.code, 'DELIVERY_CONFIRMATION_MISMATCH')


if __name__ == '__main__':
    unittest.main()

"""Mode-aware readiness. This probes tools, never the model's permissions."""
from __future__ import annotations
import importlib
import importlib.metadata
from .common import *


def selection(cfg, delivery_mode=None, host=None, entry_mode=None):
    values = {'delivery_mode': delivery_mode or cfg.get('delivery_mode', 'editable'),
              'host': host or cfg.get('host', 'auto'),
              'entry_mode': entry_mode or cfg.get('entry_mode', 'chat')}
    allowed = {'delivery_mode': ('mp4', 'editable'), 'host': ('auto', 'codex', 'deepseek'),
               'entry_mode': ('chat', 'wizard')}
    for key, options in allowed.items():
        if values[key] not in options:
            raise EditError('INVALID_MODE', f'{key} 必须为 '+', '.join(options))
    return values


def dependency_state(cfg, entry_mode=None, delivery_mode=None):
    selected = selection(cfg, delivery_mode=delivery_mode, entry_mode=entry_mode)
    required = ['numpy', 'PIL', 'fontTools']
    if selected['entry_mode'] == 'wizard': required.append('tkinter')
    if selected['delivery_mode'] == 'editable': required.append('pyJianYingDraft')
    if cfg.get('transcription_required', False): required.append('faster_whisper')
    modules, errors = {}, {}
    for name in ('tkinter', 'numpy', 'PIL', 'fontTools', 'faster_whisper', 'pyJianYingDraft'):
        try:
            # Do not import heavy optional/native libraries on the MP4 path.
            available = importlib.util.find_spec(name) is not None
            if available and name in required:
                module = importlib.import_module(name)
                if name == 'pyJianYingDraft':
                    available = (importlib.metadata.version(name) == '0.3.0'
                                 and hasattr(module, 'JianyingDraftCryptoCodec'))
            modules[name] = available
        except Exception as exc:
            modules[name] = False
            errors[name] = f'{type(exc).__name__}: {exc}'
    return modules, [name for name in required if not modules[name]], errors


def application_state(cfg, selected):
    """An explicit host identifies the assistant already running this command."""
    if os.name != 'nt':
        available = [name for name, command in (('codex', 'codex'), ('deepseek', 'dsh')) if shutil.which(command)]
        host = selected['host'] if selected['host'] != 'auto' else (available[0] if available else None)
        return {'ready': bool(host), 'selected_host': host, 'apps': [], 'problems': [] if host else ['请指定当前使用的助手：codex 或 deepseek。']}
    with tempfile.TemporaryDirectory(prefix='video-edit-apps-') as tmp:
        result, config = Path(tmp)/'applications.json', Path(tmp)/'machine.json'
        write(config, cfg)
        arguments = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                     ROOT/'scripts/application-worker.ps1', '-Root', ROOT, '-Result', result,
                     '-ConfigPath', config, '-DeliveryMode', selected['delivery_mode'],
                     '-HostName', selected['host'], '-ActiveHost']
        try: run(arguments, timeout=45)
        except EditError:
            if not result.is_file():
                return {'ready': False, 'apps': [], 'problems': ['软件扫描未完成，请运行本机环境检查。']}
        return read(result)


def doctor(cfg, delivery_mode=None, host=None, entry_mode=None):
    from . import __version__
    selected = selection(cfg, delivery_mode, host, entry_mode)
    modules, missing, errors = dependency_state(cfg, selected['entry_mode'], selected['delivery_mode'])
    problems = ['缺少 Python 组件：'+name for name in missing]
    skill_files = {name: (ROOT/name).is_file() for name in ('SKILL.md', 'scripts/video_tool.py')}
    if not all(skill_files.values()): problems.append('Skill 文件不完整，请重新安装 video-edit。')
    applications = application_state(cfg, selected)
    if not applications.get('ready'): problems += applications.get('problems') or ['所选助手或剪映尚未准备好，请运行安装向导。']
    for key in ('ffmpeg', 'ffprobe'):
        if not cfg.get(key) or not Path(cfg[key]).is_file(): problems.append('没有找到 '+key)
    if not cfg.get('font_path') or not Path(cfg['font_path']).is_file(): problems.append('没有找到可用的默认字体，请运行自动配置环境。')
    version = None
    try: version = importlib.metadata.version('pyJianYingDraft')
    except importlib.metadata.PackageNotFoundError: pass
    native = bool(modules['pyJianYingDraft'] and version == '0.3.0'
                  and cfg.get('jianying_install_dir') and (Path(cfg['jianying_install_dir'])/'videoeditor.dll').is_file())
    mask_path = None
    if selected['delivery_mode'] == 'editable':
        if not native: problems.append('可编辑工程需要本机剪映和 0.3.0 草稿库；只要 MP4 可切换为 mp4。')
        if native:
            from .native import rectangle_mask
            mask_path = rectangle_mask(cfg, False)
    model = model_path(cfg)
    transcription = bool(model and modules['faster_whisper'])
    if cfg.get('transcription_required', False) and not transcription:
        problems.append('此次需要语音识别，请按需安装本地识别组件和模型。')
    graphical, graphical_error = False, None
    if selected['entry_mode'] == 'wizard' and modules['tkinter']:
        try:
            run([sys.executable, '-c', 'import tkinter as t;r=t.Tk();r.withdraw();r.update_idletasks();r.destroy()'], timeout=20)
            graphical = True
        except Exception as exc:
            graphical_error = str(exc)
            problems.append('素材向导无法启动本地窗口；可改用 chat 入口，在对话中提供路径。')
    voices = []
    if cfg.get('voiceover_required', False):
        if os.name == 'nt':
            try:
                result = run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ROOT/'scripts/voices.ps1'], timeout=30)
                voices = json.loads(result.stdout.decode('utf-8-sig'))
            except Exception: pass
        if not voices: problems.append('此次需要配音，但未找到可用的系统声音；请配置声音或选择不配音。')
    from .typography import fonts, PRESETS
    catalog = fonts(cfg) if modules['PIL'] else {}
    return {'ready': not problems, **selected, 'python': sys.executable, 'python_version': sys.version.split()[0],
            'skill_installation': {'version': __version__, 'root': str(ROOT), 'files': skill_files,
                'installed_files_ready': all(skill_files.values()), 'loaded_by_host': 'unknown; 请由当前助手确认已读 SKILL.md'},
            'applications': applications, 'dependencies': modules, 'dependency_errors': errors,
            'writer_version': version, 'ffmpeg': cfg.get('ffmpeg'), 'ffprobe': cfg.get('ffprobe'),
            'jianying_install_dir': cfg.get('jianying_install_dir'), 'whisper_model': model,
            'offline_voices': voices, 'graphical_error': graphical_error, 'rectangle_mask_dir': mask_path,
            'typography': {'presets': list(PRESETS), 'installed_font_count': len(catalog),
                'available_families': sorted({v['family'] for v in catalog.values()}, key=str.casefold),
                'curated_fonts': [v for v in catalog.values() if v.get('curated')],
                'font_files_bundled': any(v.get('curated') for v in catalog.values())},
            'quality': {'native_media': 'byte_identical_originals', 'default_policy': 'preserve_source',
                'preview_mode': cfg.get('preview_mode', 'full_quality'), 'preview_lossless': False,
                'preview_color_output': 'SDR', 'source_hdr_preserved': True, 'lossy_encoding': 'final_mp4_only'},
            'capabilities': {'scope': 'main edit-plan schema1.0; derived technique assets have a separate interface',
                'mp4_without_jianying': True, 'native_editable_draft': native,
                'graphical_wizard': graphical, 'graphical_wizard_checked': selected['entry_mode'] == 'wizard',
                'local_transcription': transcription, 'offline_voiceover': bool(voices),
                'voiceover_checked': bool(cfg.get('voiceover_required', False)),
                'segmented_speed': True, 'editable_masks': native and bool(mask_path),
                'independent_text_audio': native, 'explicit_audio_layers': True, 'dense_frame_evidence': True,
                'host_vision': 'unknown; 由宿主实际开放的看图工具确认',
                'host_delegation': 'unknown; 由宿主实际开放的子智能体工具确认',
                'semantic_selection': '必须由实际查看帧和可用转录的助手完成',
                'optical_flow': False, 'motion_tracking': False, 'complex_matting': False, 'continuous_speed_curve': False},
            'technique_assets': {'schema_version': 'technique.2.0', 'interface': 'scripts/technique_tool.py',
                'continuous_speed_curve': True, 'animated_transforms': True, 'alpha_masks': True,
                'output': 'silent QTRLE ARGB MOV plus parameter sidecars', 'native_effect_parameter_roundtrip': False,
                'native_export': {'interface': 'export-jianying / native-capabilities',
                    'native_layers_available': native, 'preflight_per_spec_required': True,
                    'derived_fallback_opt_in': True, 'editor_ui_verified_by_doctor': False},
                'explicit_image_normalization': 'normalize-image: declared sRGB or actual embedded ICC to new BT.709 PNG',
                'render_verified_by_doctor': False, 'note': '实现能力；先校验与渲染，再审看并登记派生素材，继续主流程。'},
            'problems': problems, 'note': 'ready 仅表示所选模式运行依赖就绪；不证明模型视觉权限、Skill 已加载或剪映界面验收。'}

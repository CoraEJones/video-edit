from __future__ import annotations
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.mkv', '.avi', '.mts', '.m2ts', '.webm', '.ogv'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}

class EditError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code, self.details = code, details or {}

def resolve_path(value):
    """Resolve the same expanded path in request guards and actual file I/O."""
    return Path(os.path.expandvars(str(value))).expanduser().resolve()

def read(path):
    try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except json.JSONDecodeError as exc:raise EditError('INVALID_JSON','文件不是有效的 JSON。',{'path':str(path),'line':exc.lineno})

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False, suffix='.tmp') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        temporary = Path(f.name)
    temporary.replace(path)

def run(args, timeout=600, **kwargs):
    p = subprocess.run([str(a) for a in args], capture_output=True, timeout=timeout,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0, **kwargs)
    if p.returncode:
        raise EditError('PROCESS_FAILED', '处理程序没有成功完成。', {
            'program': str(args[0]), 'exit_code': p.returncode,
            'stderr': p.stderr.decode('utf-8', 'replace')[-3500:]})
    return p

def progress(message):
    print(message, file=sys.stderr, flush=True)

@lru_cache(maxsize=8)
def _filter_script_option(ffmpeg):
    """FFmpeg 7 introduced option files; 9 removed filter_complex_script."""
    banner = run([ffmpeg, '-version'], timeout=30).stdout.decode('utf-8', 'replace')
    version = re.search(r'^ffmpeg version (?:n)?(\d+)\.', banner, re.M)
    if version:
        modern = int(version.group(1)) >= 7
    else:
        # Git/nightly builds often have no release number in their banner.
        library = re.search(r'libavutil\s+(\d+)\.', banner)
        if not library:
            raise EditError('FFMPEG_VERSION_UNKNOWN', '无法识别 FFmpeg 版本。', {'program': str(ffmpeg)})
        modern = int(library.group(1)) >= 59
    return '-/filter_complex' if modern else '-filter_complex_script'

def filter_script_args(ffmpeg, path):
    # Keep graphs on disk: hundreds of layers can exceed Windows argv limits.
    return [_filter_script_option(str(ffmpeg)), str(path)]

def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def binary(name, configured=None):
    if configured:
        p = Path(os.path.expandvars(configured)).expanduser()
        if p.is_file():
            return str(p.resolve())
    found = shutil.which(name)
    if found:
        return found
    if os.name == 'nt':
        root = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft/WinGet/Packages'
        matches = sorted(root.glob(f'Gyan.FFmpeg*/**/{name}.exe')) if root.is_dir() else []
        if matches:
            return str(matches[-1])
    return None

def install_dir(preferred=None):
    roots = []
    if preferred:
        p = Path(os.path.expandvars(preferred)).expanduser()
        if (p / 'videoeditor.dll').is_file():
            return str(p.resolve())
        roots += [p, p.parent]
    for env in ('LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)'):
        if os.environ.get(env):
            base = Path(os.environ[env])
            roots += [base / 'JianyingPro', base / 'Programs/JianyingPro']
    if os.name == 'nt':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key in (r'Software\Microsoft\Windows\CurrentVersion\Uninstall\JianyingPro',
                        r'Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\JianyingPro'):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        for field in ('InstallLocation', 'DisplayIcon', 'UninstallString'):
                            try:
                                raw = str(winreg.QueryValueEx(k, field)[0]).strip().strip('"').split(',')[0].strip('"')
                                if raw:
                                    roots.append(Path(raw).parent if raw.lower().endswith('.exe') else Path(raw))
                            except OSError:
                                pass
                except OSError:
                    pass
    candidates = []
    for root in roots:
        for container in (root, root / 'Apps'):
            if (container / 'videoeditor.dll').is_file():
                candidates.append(container)
            if container.is_dir():
                candidates += [p for p in container.iterdir() if p.is_dir() and (p/'videoeditor.dll').is_file()]
    if not candidates:
        return None
    return str(max(candidates, key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.name))).resolve())

def load_config(path=None):
    cfg = read(ROOT/'config.example.json')
    local = Path(path or os.environ.get('VIDEO_EDIT_CONFIG', ROOT/'config.local.json'))
    if (path or os.environ.get('VIDEO_EDIT_CONFIG')) and not local.is_file():
        raise EditError('CONFIG_NOT_FOUND','指定的机器配置文件不存在。',{'path':str(local)})
    if local.is_file():
        cfg.update(read(local))
    for key, value in list(cfg.items()):
        if isinstance(value, str) and value:
            cfg[key] = os.path.expandvars(value)
    cfg['ffmpeg'] = binary('ffmpeg', cfg.get('ffmpeg'))
    cfg['ffprobe'] = binary('ffprobe', cfg.get('ffprobe'))
    cfg['jianying_install_dir'] = install_dir(cfg.get('jianying_install_dir'))
    cfg['jianying_user_data'] = cfg.get('jianying_user_data') or str(Path(os.environ.get('LOCALAPPDATA', Path.home()))/'JianyingPro/User Data')
    cfg['font_path'] = cfg.get('font_path') or str(Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts/msyh.ttc')
    return cfg

def require_binary(cfg, key):
    if not cfg.get(key):
        raise EditError('MISSING_DEPENDENCY', f'没有找到 {key}，请先运行环境检查。', {'dependency': key})
    return cfg[key]

def model_path(cfg):
    if cfg.get('whisper_model_dir') and all((Path(cfg['whisper_model_dir'])/f).is_file() for f in ('model.bin','config.json','tokenizer.json','vocabulary.txt')):
        return cfg['whisper_model_dir']
    caches = [Path(cfg['model_cache'])] if cfg.get('model_cache') else []
    for p in ROOT.parents:
        caches.append(p/'.tools/media-models')
    caches.append(Path.home()/'.cache/huggingface/hub')
    for cache in caches:
        for candidate in sorted(cache.glob('models--Systran--faster-whisper-small/snapshots/*')):
            if all((candidate/f).is_file() for f in ('model.bin','config.json','tokenizer.json','vocabulary.txt')):
                return str(candidate.resolve())
    return None

def probe(path, cfg):
    obj = json.loads(run([require_binary(cfg,'ffprobe'), '-v','error','-show_format','-show_streams','-of','json',path], timeout=90).stdout)
    streams = obj.get('streams', [])
    v = next((s for s in streams if s.get('codec_type') == 'video'), {})
    rate = v.get('avg_frame_rate', '0/1')
    try:
        a,b = rate.split('/'); fps = float(a)/float(b)
    except (ValueError, ZeroDivisionError):
        fps = 0
    rotation = next((float(s.get('rotation',0)) for s in v.get('side_data_list',[]) if 'rotation' in s), float(v.get('tags',{}).get('rotate',0)))
    width,height = v.get('width',0),v.get('height',0)
    if abs(rotation)%180 == 90:
        width,height = height,width
    return {'duration':float(obj.get('format',{}).get('duration',v.get('duration',0)) or 0),
            'width':width,'height':height,'fps':fps,'rotation':rotation,
            'has_audio':any(s.get('codec_type')=='audio' for s in streams),
            'color_transfer':v.get('color_transfer'),'color_primaries':v.get('color_primaries'),
            'color_space':v.get('color_space'),'color_range':v.get('color_range'),
            'codec_name':v.get('codec_name'),'pix_fmt':v.get('pix_fmt'),
            'bit_rate':v.get('bit_rate'),'bits_per_raw_sample':v.get('bits_per_raw_sample'),
            'frame_rate_fraction':rate,'coded_width':v.get('width',0),'coded_height':v.get('height',0),
            'sample_aspect_ratio':v.get('sample_aspect_ratio','1:1')}

def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' .')[:90]
    if not name or name in ('.','..') or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM\d|LPT\d)(\..*)?', name):
        raise EditError('INVALID_NAME', '请使用普通文字为作品命名。')
    return name

"""Local sound catalogue, bounded CC0 downloads, and early rhythm candidates.

This helper never chooses music by filename and never treats an onset as a beat.
Run from either Codex or another harness with the skill's configured Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
import sys
import tempfile
import urllib.parse
import urllib.request

from video_edit.common import ROOT, EditError, binary, read, run, sha256, write

DEFAULT_CATALOG = ROOT / 'assets/sound-library/catalog.json'


def config(args):
    path = Path(args.config) if args.config else ROOT / 'config.local.json'
    value = read(path) if path.is_file() else {}
    for name in ('ffmpeg', 'ffprobe'):
        value[name] = binary(name, value.get(name))
        if not value[name]:
            raise EditError('AUDIO_TOOL_MISSING', f'没有找到 {name}，请先运行技能环境检查。')
    return value


def probe(path, cfg):
    result = json.loads(run([cfg['ffprobe'], '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=codec_name,sample_rate,channels:format=duration',
        '-of', 'json', path]).stdout)
    streams = result.get('streams', [])
    duration = float(result.get('format', {}).get('duration', 0))
    if not streams or not math.isfinite(duration) or duration <= 0:
        raise EditError('INVALID_AUDIO', '文件没有有效音轨或时长。', {'path': str(path)})
    return dict(streams[0], duration_seconds=round(duration, 6))


def local_path(catalog_path, entry):
    root = catalog_path.parent.resolve()
    path = (root / entry['file']).resolve()
    if not path.is_relative_to(root):
        raise EditError('CATALOG_PATH', '声音文件路径必须在音效库内部。')
    return path


def select(catalog, ids=None, query=''):
    entries = catalog['sounds']
    if ids:
        unknown = set(ids) - {e['id'] for e in entries}
        if unknown:
            raise EditError('SOUND_NOT_FOUND', '音效编号不存在。', {'ids': sorted(unknown)})
        entries = [e for e in entries if e['id'] in ids]
    words = query.casefold().split()
    return [e for e in entries if all(w in json.dumps(e, ensure_ascii=False).casefold() for w in words)]


def verify_file(path, entry, cfg, decode=True):
    if not path.is_file():
        raise EditError('SOUND_MISSING', '音效还没有下载。', {'id': entry['id']})
    digest = sha256(path)
    if not entry.get('sha256') or digest != entry['sha256']:
        raise EditError('SOUND_HASH_MISMATCH', '声音文件与目录校验值不一致。', {'id': entry['id']})
    metadata = probe(path, cfg)
    if decode:
        run([cfg['ffmpeg'], '-v', 'error', '-xerror', '-i', path, '-map', '0:a:0', '-f', 'null', '-'])
    return dict(id=entry['id'], path=str(path), sha256=digest, bytes=path.stat().st_size,
                full_decode_ok=decode, **metadata)


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urllib.parse.urlparse(req.full_url), urllib.parse.urlparse(newurl)
        if new.scheme != 'https' or new.hostname != old.hostname:
            raise EditError('DOWNLOAD_REDIRECT', '下载被重定向到另一域名，请重新核对来源。')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_entry(catalog_path, entry, cfg, max_bytes):
    # This catalogue is curated by an agent after reviewing the original page.
    # A search-engine "royalty-free" label alone is insufficient.
    required = ('source_page', 'download_url', 'author', 'license_url', 'license_checked_at', 'license_evidence')
    if entry.get('license') != 'CC0-1.0' or any(not entry.get(key) for key in required):
        raise EditError('LICENSE_NOT_VERIFIED', '仅下载已核对原发布页与 CC0 许可的条目。')
    page = urllib.parse.urlparse(entry['source_page'])
    media = urllib.parse.urlparse(entry['download_url'])
    if page.scheme != 'https' or media.scheme != 'https' or page.hostname != media.hostname:
        raise EditError('DOWNLOAD_SOURCE', '下载地址须来自已核对原发布页的同一 HTTPS 域名。')
    if media.username or media.password:
        raise EditError('DOWNLOAD_SOURCE', '不接受带登录信息的下载地址。')
    path = local_path(catalog_path, entry)
    if path.exists():
        return dict(status='cached', **verify_file(path, entry, cfg))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        opener = urllib.request.build_opener(SameHostRedirect())
        request = urllib.request.Request(entry['download_url'], headers={'User-Agent': 'video-edit-sound-library/1.0'})
        with opener.open(request, timeout=30) as response, tempfile.NamedTemporaryFile(
                dir=path.parent, suffix=path.suffix, delete=False) as target:
            temporary = Path(target.name)
            count = 0
            while block := response.read(65536):
                count += len(block)
                if count > max_bytes:
                    raise EditError('DOWNLOAD_TOO_LARGE', '文件超过本次下载大小上限。')
                target.write(block)
        metadata = probe(temporary, cfg)
        run([cfg['ffmpeg'], '-v', 'error', '-xerror', '-i', temporary, '-map', '0:a:0', '-f', 'null', '-'])
        digest = sha256(temporary)
        if entry.get('sha256') and entry['sha256'] != digest:
            raise EditError('SOUND_HASH_MISMATCH', '重新下载的内容已变化，请重新核对原发布页。')
        temporary.replace(path)
        entry.update(sha256=digest, bytes=path.stat().st_size, probe=metadata,
                     downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                     status='downloaded', full_decode_ok=True)
        return dict(id=entry['id'], status='downloaded', path=str(path), **metadata)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def analyze_file(args, cfg):
    from video_edit.sound import detect_beats
    path = Path(args.file).resolve()
    metadata = probe(path, cfg)
    if not math.isfinite(args.start) or args.start < 0 or args.start >= metadata['duration_seconds']:
        raise EditError('AUDIO_RANGE', '开始时间超出音频范围。')
    if not math.isfinite(args.duration) or not 0 < args.duration <= 1800:
        raise EditError('AUDIO_RANGE', '一次分析时长应在 0 到 1800 秒之间。')
    length = min(args.duration, metadata['duration_seconds'] - args.start)
    with tempfile.TemporaryDirectory(prefix='video-edit-rhythm-') as scratch:
        normalized = Path(scratch) / 'analysis.wav'
        run([cfg['ffmpeg'], '-v', 'error', '-ss', args.start, '-i', path, '-t', length,
             '-vn', '-ac', '2', '-ar', '48000', '-y', normalized])
        result = detect_beats(normalized)
    onsets = [round(t + args.start, 6) for t in result.get('beats', [])]
    result.pop('beats', None)
    value = dict(schema_version='1.0', file=str(path), sha256=sha256(path),
        time_basis='source_file_seconds', analyzed_start=args.start, analyzed_duration=length,
        candidate_onsets=onsets, downbeats=[], phrases=[], listening_review='required',
        editorial_note='候选起音不是确认鼓点。试听后标记重拍和乐句，再按音轨起点/入点映射到剪辑时间线。',
        audio=metadata, detector=result)
    if args.output:
        write(args.output, value)
    return value


def main():
    # Windows' locale encoding otherwise corrupts Chinese JSON on piped stdout.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='机器配置 JSON；默认技能根目录的 config.local.json')
    parser.add_argument('--catalog', default=str(DEFAULT_CATALOG))
    sub = parser.add_subparsers(dest='command', required=True)
    search = sub.add_parser('search', help='在已核对的本地音效目录中按中文或英文标签检索')
    search.add_argument('--query', default='')
    for name in ('fetch', 'verify'):
        command = sub.add_parser(name)
        group = command.add_mutually_exclusive_group(required=True)
        group.add_argument('--id', action='append')
        group.add_argument('--all', action='store_true')
        if name == 'fetch':
            command.add_argument('--max-mb', type=float, default=15)
    analysis = sub.add_parser('analyze', help='在精剪前生成本地音乐文件的候选起音时间')
    analysis.add_argument('--file', required=True)
    analysis.add_argument('--start', type=float, default=0)
    analysis.add_argument('--duration', type=float, default=300)
    analysis.add_argument('--output')
    args = parser.parse_args()
    try:
        if args.command == 'analyze':
            result = analyze_file(args, config(args))
        else:
            catalog_path = Path(args.catalog).resolve()
            catalog = read(catalog_path)
            entries = select(catalog, getattr(args, 'id', None), getattr(args, 'query', ''))
            if args.command == 'search':
                result = [dict(e, absolute_path=str(local_path(catalog_path, e)),
                               available=local_path(catalog_path, e).is_file()) for e in entries]
            else:
                cfg = config(args)
                result, failures = [], []
                if args.command == 'fetch' and (not math.isfinite(args.max_mb) or args.max_mb <= 0):
                    raise EditError('DOWNLOAD_LIMIT', '下载大小上限必须为正数。')
                for entry in entries:
                    try:
                        if args.command == 'fetch':
                            result.append(fetch_entry(catalog_path, entry, cfg, int(args.max_mb * 1024**2)))
                            write(catalog_path, catalog)
                        else:
                            result.append(verify_file(local_path(catalog_path, entry), entry, cfg))
                    except (EditError, OSError, ValueError) as exc:
                        failures.append({'id': entry['id'], 'message': str(exc),
                                         'code': getattr(exc, 'code', 'AUDIO_FAILED')})
                if failures:
                    raise EditError('PARTIAL_AUDIO_FAILURE', '部分音效未处理成功。', {'completed': result, 'failed': failures})
        print(json.dumps({'ok': True, 'code': 'OK', 'data': result}, ensure_ascii=False))
        return 0
    except (EditError, OSError, ValueError) as exc:
        print(json.dumps({'ok': False, 'code': getattr(exc, 'code', 'AUDIO_FAILED'),
                          'message': str(exc), 'data': getattr(exc, 'details', {})}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())

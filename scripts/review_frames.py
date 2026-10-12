"""Extract timestamped evidence frames; this tool does not perform visual analysis."""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import sys

from video_edit.common import EditError, load_config, progress, read, require_binary, run, write


MAX_INTERVAL_SECONDS = 120
HARD_MAX_FRAMES = 600


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise EditError('INVALID_ARGUMENT', message)


def finite(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise EditError('INVALID_ARGUMENT', f'{name} 必须是有限数字。')
    if not math.isfinite(number):
        raise EditError('INVALID_ARGUMENT', f'{name} 必须是有限数字。')
    return number


def timecode(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}'


def source_row(inventory, ident):
    rows = read(inventory)
    if not isinstance(rows, list):
        raise EditError('INVALID_INVENTORY', 'inventory 必须是 analyze 生成的素材列表。')
    matches = [row for row in rows if isinstance(row, dict) and row.get('id') == ident]
    if len(matches) != 1:
        raise EditError('ASSET_NOT_UNIQUE', '素材 id 必须在 inventory 中恰好出现一次。', {'id': ident, 'matches': len(matches)})
    row = matches[0]
    path = row.get('absolute_path')
    if not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file():
        raise EditError('MEDIA_NOT_FOUND', '该素材的 absolute_path 必须指向现有文件。')
    source = Path(path).resolve()
    fingerprint = row.get('fingerprint')
    if fingerprint:
        stat = source.stat()
        if fingerprint != {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}:
            raise EditError('SOURCE_CHANGED', '素材在建立 inventory 后发生变化，请先重新分析。')
    if row.get('kind') not in ('video', 'image'):
        raise EditError('UNSUPPORTED_MEDIA', '此工具只处理视频或静态图片。')
    return row, source


def video_info(source, cfg):
    info = json.loads(run([
        require_binary(cfg, 'ffprobe'), '-v', 'error', '-show_format', '-show_streams',
        '-of', 'json', source,
    ], timeout=90).stdout)
    stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video' and not s.get('disposition', {}).get('attached_pic')), None)
    if not stream:
        raise EditError('NO_VIDEO_STREAM', '素材中没有可解码的视频流。')
    fmt = info.get('format', {})
    duration = finite(fmt.get('duration', stream.get('duration')), '素材时长')
    origin = finite(fmt.get('start_time', stream.get('start_time', 0)), '素材起始时间戳')
    return stream, duration, origin


def parse_timestamps(stderr, count, origin):
    # pts_time is rounded by ffmpeg; integer PTS * time_base retains its precision.
    base_match = re.search(r'config in time_base:\s*([0-9]+/[0-9]+)', stderr)
    if not base_match:
        raise EditError('TIMESTAMP_UNAVAILABLE', '解码器没有返回帧时间基，不能可靠标注时码。')
    base = Fraction(base_match.group(1))
    records = {}
    for match in re.finditer(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:', stderr):
        number, pts = int(match.group(1)), int(match.group(2))
        records[number] = {'pts': pts, 'time_base': str(base), 'source_time': float(pts * base) - origin}
    if any(i not in records for i in range(count)):
        raise EditError('TIMESTAMP_MISMATCH', '图片数量与解码时码不一致；本次结果不可用于剪辑。')
    return [records[i] for i in range(count)]


def contact_sheets(frames, output, cfg):
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path(cfg['font_path'])
    font = ImageFont.truetype(str(font_path), 17) if font_path.is_file() else ImageFont.load_default()
    sheets = []
    for first in range(0, len(frames), 12):
        page = frames[first:first + 12]
        sheet = Image.new('RGB', (990, 228 * math.ceil(len(page) / 3)), '#182333')
        draw = ImageDraw.Draw(sheet)
        for index, frame in enumerate(page):
            x, y = (index % 3) * 330, (index // 3) * 228
            with Image.open(frame['path']) as source:
                pic = source.convert('RGB')
                pic.thumbnail((322, 184))
                sheet.paste(pic, (x + (330 - pic.width) // 2, y + 4 + (184 - pic.height) // 2))
            draw.text((x + 8, y + 196), f"#{frame['index']:04d}  {frame['timecode']}", font=font, fill='white')
        dest = output / f'contact_{first // 12 + 1:03d}.jpg'
        sheet.save(dest, quality=91)
        sheets.append(str(dest))
    return sheets


def extract(args):
    from PIL import Image, ImageOps
    if not 1 <= args.max_frames <= HARD_MAX_FRAMES:
        raise EditError('INVALID_ARGUMENT', f'--max-frames 必须在 1 到 {HARD_MAX_FRAMES} 之间。')
    row, source = source_row(args.inventory, args.id)
    output = Path(args.output).expanduser().resolve()
    if output.exists():
        raise EditError('OUTPUT_EXISTS', '输出目录必须是新目录；不会覆盖已有结果。', {'path': str(output)})
    # No source path is ever opened for writing. Reject output ancestors explicitly.
    if output == source or output in source.parents or output in Path(args.inventory).resolve().parents:
        raise EditError('OUTPUT_CONFLICT', '输出目录不能包含原始素材或 inventory。')
    cfg = load_config(args.config)
    warnings = []
    if row['kind'] == 'image':
        if args.start is not None or args.end is not None or args.fps is not None or args.every_frame:
            raise EditError('IMAGE_RANGE_UNSUPPORTED', '静态图片只产生一帧，请省略 --start、--end、--fps 和 --every-frame。')
        with Image.open(source) as image:
            if getattr(image, 'n_frames', 1) > 1:
                raise EditError('ANIMATED_IMAGE_UNSUPPORTED', '动态图片不是静态照片，请先作为视频素材导入。')
            picture = ImageOps.exif_transpose(image).convert('RGB')
            if not args.native_size:
                picture.thumbnail((960, 960))
        mode, start, end, fps, origin = 'single_image', 0, 0, None, None
    else:
        if args.start is None or args.end is None:
            raise EditError('RANGE_REQUIRED', '视频必须明确指定 --start 和 --end（源素材秒数，结束点不包含）。')
        start, end = finite(args.start, '--start'), finite(args.end, '--end')
        if start < 0 or end <= start or end - start > MAX_INTERVAL_SECONDS:
            raise EditError('INVALID_RANGE', f'需满足 0 <= start < end，单次区间最多 {MAX_INTERVAL_SECONDS} 秒。')
        fps = None if args.every_frame else finite(args.fps if args.fps is not None else 2, '--fps')
        if fps is not None and not 0 < fps <= 60:
            raise EditError('INVALID_ARGUMENT', '--fps 必须大于 0 且不超过 60。')
        stream, duration, origin = video_info(source, cfg)
        if end > duration + 0.000001:
            raise EditError('RANGE_OUT_OF_BOUNDS', '区间超出源素材时长，不会静默缩短。', {'duration': duration, 'start': start, 'end': end})
        mode = 'every_decoded_frame' if args.every_frame else 'sampled_actual_frames'
        if fps:
            warnings.append('抽样间隔是相邻实际帧之间的最小间隔；--fps 不是原片帧率，也不代表逐帧覆盖。')
        warnings.append('时码相对于容器起始时间；使用实际 PTS。VFR 保留可解码帧，不复制或补出固定帧率画面。')
        require_binary(cfg, 'ffmpeg')
    output.mkdir(parents=True, exist_ok=False)
    frames_dir = output / 'frames'
    frames_dir.mkdir()
    try:
        progress(f"提取 {args.id}：{mode}，输出上限 {args.max_frames} 帧")
        if row['kind'] == 'image':
            picture.save(frames_dir / 'frame_000001.jpg', quality=94)
            stamps = [{'pts': None, 'time_base': None, 'source_time': 0.0}]
        else:
            start_raw, end_raw = start + origin, end + origin
            selection = f'gte(t\\,{start_raw:.12f})*lt(t\\,{end_raw:.12f})'
            if fps:
                selection += f'*(isnan(prev_selected_t)+gte(t-prev_selected_t\\,{1 / fps - 1e-9:.12f}))'
            filters = f'select={selection},showinfo'
            if not args.native_size:
                filters += ",scale='min(960,iw)':'min(960,ih)':force_original_aspect_ratio=decrease"
            result = run([
                cfg['ffmpeg'], '-hide_banner', '-nostdin', '-loglevel', 'info', '-xerror',
                '-ss', f'{start:.12f}', '-t', f'{end - start:.12f}', '-copyts', '-i', source,
                '-map', f"0:{stream['index']}", '-an', '-sn', '-dn', '-vf', filters,
                '-fps_mode', 'passthrough', '-frames:v', args.max_frames + 1,
                '-threads', '2', '-q:v', '2', '-n', frames_dir / 'frame_%06d.jpg',
            ], timeout=300)
            files = sorted(frames_dir.glob('frame_*.jpg'))
            if len(files) > args.max_frames:
                raise EditError('FRAME_LIMIT_EXCEEDED', '该区间超过帧数上限；请缩短区间或降低抽样速率。已有图片仅为不完整结果。', {'max_frames': args.max_frames})
            if not files:
                raise EditError('NO_FRAMES', '指定区间没有解码出图片；不能声称已检查该区间。')
            stamps = parse_timestamps(result.stderr.decode('utf-8', 'replace'), len(files), origin)
        frames = []
        for index, (path, stamp) in enumerate(zip(sorted(frames_dir.glob('frame_*.jpg')), stamps), 1):
            seconds = stamp['source_time']
            if row['kind'] == 'video' and not start - 1e-7 <= seconds < end + 1e-7:
                raise EditError('TIMESTAMP_OUT_OF_RANGE', '返回帧时码不在指定区间内，结果不可用于剪辑。')
            frames.append({'index': index, 'path': str(path), **stamp, 'timecode': timecode(seconds)})
        sheets = contact_sheets(frames, output, cfg)
        manifest = {
            'schema': 'video-edit.frame-review/v1', 'status': 'ready_for_visual_review',
            'asset_id': args.id, 'source': str(source), 'inventory': str(Path(args.inventory).resolve()),
            'source_interval': {'start': start, 'end': end, 'end_exclusive': True},
            'mode': mode, 'sample_fps': fps, 'frame_count': len(frames), 'max_frames': args.max_frames,
            'source_timestamp_origin': origin, 'extraction_completed': True,
            'native_size': args.native_size,
            'visual_review_completed': False, 'frames': frames, 'contact_sheets': sheets,
            'coverage_note': ('已导出指定区间中解码器返回的每个视频帧；尚未进行任何人工或模型视觉查看。'
                              if args.every_frame else '仅导出所列图片，不能推断未抽样时刻，也不代表已进行视觉分析。'),
            'warnings': warnings,
        }
        write(output / 'frame-review.json', manifest)
        return {'ok': True, 'manifest': str(output / 'frame-review.json'), 'mode': mode,
                'frame_count': len(frames), 'contact_sheets': sheets,
                'visual_review_completed': False, 'warnings': warnings}
    except Exception as exc:
        write(output / 'INCOMPLETE.json', {'status': 'failed', 'extraction_completed': False,
              'visual_review_completed': False, 'error': str(exc),
              'note': '此目录只含不完整的诊断产物，不可当作完整帧覆盖证据；重试须使用新输出目录。'})
        if isinstance(exc, EditError):
            exc.details['incomplete_output'] = str(output)
        raise


def main(argv=None):
    parser = JsonArgumentParser(description=__doc__)
    parser.add_argument('--inventory', required=True)
    parser.add_argument('--id', required=True, help='inventory 中的素材 id')
    parser.add_argument('--start', help='源素材开始秒数')
    parser.add_argument('--end', help='源素材结束秒数，不包含结束点')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--fps', help='抽样最大速率，默认 2；使用真实帧，不重采样')
    selection.add_argument('--every-frame', action='store_true', help='导出指定区间全部可解码帧')
    parser.add_argument('--max-frames', type=int, default=240, help='输出上限，默认 240，最多 600；超限报错')
    parser.add_argument('--native-size', action='store_true', help='保留源画面分辨率，用于复核焦点与细节；默认最长边960且不放大')
    parser.add_argument('--output', required=True, help='新的结果目录，不可已存在')
    parser.add_argument('--config', help='video-edit 配置文件')
    try:
        result = extract(parser.parse_args(argv))
    except EditError as exc:
        result = {'ok': False, 'error': {'code': exc.code, 'message': str(exc), 'details': exc.details}}
    except Exception as exc:
        result = {'ok': False, 'error': {'code': 'EXTRACTION_FAILED', 'message': str(exc)}}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())

"""Validate review ledgers, never infer that a person/model actually watched.

The optional material-analysis link makes source ranges and selected segments
auditable on disk without loading the whole collection into an agent's context.
"""
from __future__ import annotations
import math
from pathlib import Path
import re
from .common import EditError, read


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _path(raw, base):
    path = Path(raw)
    return path if path.is_absolute() else Path(base)/path


def _range(raw):
    return raw.get('source_start', raw.get('source_in')), raw.get('source_end', raw.get('source_out'))


def _valid_range(a, b, duration):
    return finite(a) and finite(b) and 0 <= a < b <= duration + .002


def _duration(row):
    # Older generated-image inventories used duration=0. Static images have no
    # physical source timeline; use the analyzer's five-second reference extent.
    return max(5, row['duration']) if row.get('kind') == 'image' else row['duration']


def covered(start, end, ranges):
    """Union coverage in source seconds; touching clips can satisfy one range."""
    cursor = start
    for a, b in sorted(ranges):
        if b < cursor - .002:
            continue
        if a > cursor + .002:
            return False
        cursor = max(cursor, b)
        if cursor >= end - .002:
            return True
    return False


def _evidence(item, lookup, base, where, issue, asset_id=None):
    if not isinstance(item, dict):
        issue('REVIEW_EVIDENCE_FORMAT', where, '结构化证据必须是对象，包含 asset_id、path 与源时码。')
        return None
    ident = item.get('asset_id', asset_id)
    row = lookup.get(ident) if isinstance(ident, str) else None
    if row is None:
        issue('REVIEW_EVIDENCE_ASSET', where, '证据必须关联本次清单中的素材 asset_id。')
        return None
    if asset_id is not None and ident != asset_id:
        issue('REVIEW_EVIDENCE_ASSET', where, '片段证据不能指向另一条素材。')
    raw = item.get('path')
    if not isinstance(raw, str) or not raw.strip():
        issue('REVIEW_EVIDENCE_PATH', where, '证据需要实际本地文件路径。')
    else:
        try:
            if not _path(raw, base).is_file():
                issue('REVIEW_EVIDENCE_MISSING', where, '证据文件不存在：'+raw)
        except (OSError, ValueError):
            issue('REVIEW_EVIDENCE_PATH', where, '证据文件路径无效。')
    kind = item.get('kind', 'frame' if 'time' in item else 'playback')
    if kind not in ('frame', 'playback', 'audio', 'transcript', 'contact_sheet'):
        issue('REVIEW_EVIDENCE_KIND', where, '证据种类需要 frame/playback/audio/transcript/contact_sheet。')
    if 'time' in item:
        t = item['time']
        if any(k in item for k in ('source_start', 'source_end', 'source_in', 'source_out')):
            issue('REVIEW_EVIDENCE_TIME', where, '单帧 time 与区间时码不能混用。')
        if not finite(t) or not 0 <= t <= row['duration'] + .002 or (row.get('kind') == 'image' and t != 0):
            issue('REVIEW_EVIDENCE_TIME', where, '证据时间必须是素材范围内的有限源秒数；图片 time=0。')
            return None
        return ident, t, t, kind
    a, b = _range(item)
    if not _valid_range(a, b, _duration(row)):
        issue('REVIEW_EVIDENCE_TIME', where, '证据区间需要有效 source_start/source_end，不能超出原片。')
        return None
    return ident, a, b, kind


def _analysis_index(analysis, rows, base):
    errors = []
    def issue(code, where, message):
        errors.append({'code': code, 'at': where, 'message': message})
    lookup = {r['id']: r for r in rows}
    index = {}
    if not isinstance(analysis, dict) or not isinstance(analysis.get('assets'), list):
        issue('ANALYSIS_FORMAT', 'analysis', '素材分析需要 assets 对象数组。')
        return index, errors
    if analysis.get('schema_version') not in ('material-analysis-1.0', 'material-analysis-1.1'):
        issue('ANALYSIS_SCHEMA', 'analysis.schema_version', '需要 material-analysis-1.0 或 material-analysis-1.1。')
    if analysis.get('time_basis') != 'source_seconds':
        issue('ANALYSIS_TIME_BASIS', 'analysis.time_basis', '分析时码必须声明 source_seconds。')
    seen_segments = set()
    for i, asset in enumerate(analysis['assets']):
        where = f'analysis.assets[{i}]'
        if not isinstance(asset, dict):
            issue('ANALYSIS_FORMAT', where, '素材分析项需要对象。'); continue
        ident = asset.get('id')
        row = lookup.get(ident) if isinstance(ident, str) else None
        if row is None:
            issue('ANALYSIS_ASSET', where, '分析编号必须存在于传入素材清单。'); continue
        if ident in index:
            issue('ANALYSIS_DUPLICATE_ASSET', where, '同一素材只能有一个分析项。'); continue
        if 'fingerprint' in asset and asset['fingerprint'] != row.get('fingerprint'):
            issue('ANALYSIS_SOURCE_CHANGED', where, '分析指纹与当前素材清单不一致，请重新审看。')
        if asset.get('status') not in ('reviewed', 'pending', 'failed', 'analysis_failed', 'blocked_visual', 'needs_review'):
            issue('ANALYSIS_STATUS', where, '审看状态需要 reviewed、pending、failed、analysis_failed、blocked_visual 或 needs_review。')
        coverage = asset.get('coverage', {})
        if not isinstance(coverage, dict):
            issue('ANALYSIS_COVERAGE', where, 'coverage 需要对象。'); coverage = {}
        segments = asset.get('segments', [])
        if not isinstance(segments, list):
            issue('ANALYSIS_SEGMENTS', where, 'segments 需要对象数组。'); segments = []
        segment_map, frame_points, playback = {}, {}, []
        for frame in row.get('frames', []):
            if isinstance(frame, dict) and finite(frame.get('time')) and isinstance(frame.get('path'), str):
                frame_points.setdefault(frame['time'], []).append(frame['path'])
        for j, segment in enumerate(segments):
            at = f'{where}.segments[{j}]'
            if not isinstance(segment, dict):
                issue('ANALYSIS_SEGMENTS', at, '片段需要对象。'); continue
            sid = segment.get('segment_id')
            if not isinstance(sid, str) or not sid or sid in seen_segments:
                issue('ANALYSIS_SEGMENT_ID', at, 'segment_id 需要全局唯一非空字符串。'); continue
            seen_segments.add(sid)
            a, b = segment.get('source_in'), segment.get('source_out')
            if not _valid_range(a, b, _duration(row)):
                issue('ANALYSIS_SEGMENT_RANGE', at, '片段需要原片范围内的 source_in/source_out。'); continue
            segment_map[sid] = segment
            evidence = segment.get('evidence', [])
            if not isinstance(evidence, list) or (asset.get('status') == 'reviewed' and not evidence):
                issue('ANALYSIS_SEGMENT_EVIDENCE', at, '已审片段需要非空结构化 evidence 数组。'); continue
            for k, item in enumerate(evidence):
                result = _evidence(item, lookup, base, f'{at}.evidence[{k}]', issue, ident)
                if result and result[3] == 'frame' and isinstance(item.get('path'), str):
                    frame_points.setdefault(result[1], []).append(item['path'])
        declared = coverage.get('frame_times_viewed', [])
        if not isinstance(declared, list):
            issue('ANALYSIS_COVERAGE', where+'.coverage.frame_times_viewed', '需要已查看源时码数组。'); declared = []
        viewed = []
        for j, t in enumerate(declared):
            at = f'{where}.coverage.frame_times_viewed[{j}]'
            if not finite(t) or not 0 <= t <= row['duration'] + .002:
                issue('ANALYSIS_COVERAGE_TIME', at, '已查看帧时码必须在素材范围内。'); continue
            paths = [p for pt, candidates in frame_points.items() if abs(pt-t) < .002 for p in candidates]
            if not paths or not any(_path(p, base).is_file() for p in paths):
                issue('ANALYSIS_COVERAGE_EVIDENCE', at, '已查看时码缺少存在的对应帧文件。')
            else:
                viewed.append(t)
        sheets = coverage.get('contact_sheets_viewed', [])
        if not isinstance(sheets, list):
            issue('ANALYSIS_COVERAGE', where+'.coverage.contact_sheets_viewed', '需要联系表路径数组。')
        else:
            for j, path in enumerate(sheets):
                if not isinstance(path, str) or not _path(path, base).is_file():
                    issue('REVIEW_EVIDENCE_MISSING', f'{where}.coverage.contact_sheets_viewed[{j}]', '声明查看的联系表文件不存在。')
        ranges = coverage.get('playback_ranges', [])
        if not isinstance(ranges, list):
            issue('ANALYSIS_COVERAGE', where+'.coverage.playback_ranges', '需要回放区间对象数组。'); ranges = []
        for j, raw in enumerate(ranges):
            at = f'{where}.coverage.playback_ranges[{j}]'
            if not isinstance(raw, dict):
                issue('ANALYSIS_COVERAGE', at, '回放区间需要对象。'); continue
            result = _evidence({'asset_id': ident, 'path': row['absolute_path'], 'kind': 'playback', **raw}, lookup, base, at, issue, ident)
            if result and result[1] < result[2] and result[3] == 'playback':
                playback.append((result[1], result[2]))
        # Dense sampling is recorded as sampled coverage, never full-frame QA.
        points = sorted(set(viewed))
        sampled = [(a, b) for a, b in zip(points, points[1:]) if b-a <= 1.002]
        index[ident] = {'asset': asset, 'segments': segment_map, 'ranges': playback+sampled,
                        'frame_times': points, 'playback_ranges': playback}
    return index, errors


def validate_analysis(analysis, rows, base_dir):
    """Validate one batch or whole ledger; rows may be only this batch's subset.

    There is no all-library coverage requirement here. The plan's strict link
    checks its selected ranges, and the memory compiler checks batch ownership.
    """
    return _analysis_index(analysis, rows, base_dir)[1]


def _selected_ranges(plan):
    selected = []
    for group in ('shots', 'panels', 'visual_layers'):
        for i, clip in enumerate(plan.get(group, [])):
            if str(clip.get('purpose', '')).startswith('panels_'):
                continue
            a, d, speed = clip.get('source_in', 0), clip.get('duration'), clip.get('speed', 1)
            if all(finite(v) for v in (a, d, speed)) and a >= 0 and d > 0 and speed > 0:
                selected.append((clip.get('id'), a, a+d*speed, clip, f'{group}[{i}]'))
    return selected


def validate_review(plan, rows, plan_path, issue, warnings):
    """Compatibility mode checks files/time; analysis_path adds strict linking."""
    review = plan.get('review', {})
    base, lookup = Path(plan_path).parent, {r['id']: r for r in rows}
    evidence = review.get('evidence', [])
    if isinstance(evidence, str) and evidence.strip():
        evidence = [evidence]  # Pre-1.7 plans also used one narrative string.
    if not isinstance(evidence, list):
        issue('REVIEW_EVIDENCE_FORMAT', 'review.evidence', '证据需要数组。'); evidence = []
    legacy = False
    for i, item in enumerate(evidence):
        where = f'review.evidence[{i}]'
        if isinstance(item, dict):
            _evidence(item, lookup, base, where, issue)
        elif isinstance(item, str) and item.strip():
            legacy = True
            raw = item.strip()
            # Reject obviously missing path declarations while keeping old
            # narrative review notes readable. Narrative notes are not proof.
            match = re.match(r'^(.*?\.(?:jpe?g|png|webp|mp4|mov|wav|json))(?=$|[\s#@])', raw, re.I)
            if re.match(r'^(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])', raw) or match:
                path = match[1] if match else re.split(r'[#@]', raw, maxsplit=1)[0].strip()
                if not _path(path, base).is_file():
                    issue('REVIEW_EVIDENCE_MISSING', where, '声明的证据路径不存在：'+path)
        else:
            issue('REVIEW_EVIDENCE_FORMAT', where, '证据需要非空说明或结构化对象。')
    if legacy:
        warnings.append('LEGACY_REVIEW_EVIDENCE：文字审看说明仅为兼容记录，不能证明真实审看或源区间覆盖；建议改为结构化证据。')
    selected = _selected_ranges(plan)
    wanted = plan.get('request', {}).get('must_keep_ranges', [])
    valid_wanted = []
    if not isinstance(wanted, list):
        issue('MUST_KEEP_RANGE_FORMAT', 'request.must_keep_ranges', '必留区间需要对象数组。'); wanted = []
    for i, item in enumerate(wanted):
        at = f'request.must_keep_ranges[{i}]'
        row = lookup.get(item.get('asset_id')) if isinstance(item, dict) and isinstance(item.get('asset_id'), str) else None
        if row is None:
            issue('MUST_KEEP_RANGE_ASSET', at, '必留区间必须指定真实 asset_id。'); continue
        a, b = _range(item)
        if not _valid_range(a, b, _duration(row)):
            issue('MUST_KEEP_RANGE_TIME', at, '必留区间必须是原片内的有效源时码。'); continue
        valid_wanted.append((row['id'], a, b, at))
        if row.get('kind') == 'image':
            present = any(ident == row['id'] for ident, *_ in selected)
        else:
            present = covered(a, b, [(s, e) for ident, s, e, *_ in selected if ident == row['id']])
        if not present:
            issue('MUST_KEEP_RANGE_MISSING', at, '选中镜头未完整覆盖用户指定的源区间。')
    if 'analysis_path' not in review:
        return
    raw = review['analysis_path']
    if not isinstance(raw, str) or not raw.strip():
        issue('ANALYSIS_PATH', 'review.analysis_path', '需要素材分析 JSON 路径。'); return
    path = _path(raw, base)
    if not path.is_file():
        issue('ANALYSIS_MISSING', 'review.analysis_path', '素材分析 JSON 不存在。'); return
    try:
        analysis = read(path)
    except (EditError, OSError) as exc:
        issue('ANALYSIS_FORMAT', 'review.analysis_path', str(exc)); return
    index, errors = _analysis_index(analysis, rows, path.parent)
    for error in errors:
        issue(error['code'], error['at'], error['message'])
    for ident, a, b, clip, where in selected:
        row = lookup.get(ident) if isinstance(ident, str) else None
        data = index.get(ident) if isinstance(ident, str) else None
        if row is None:
            continue
        if not data or data['asset'].get('status') != 'reviewed':
            issue('SELECTED_NOT_REVIEWED', where, '入选素材必须在分析清单中已审看。'); continue
        if row.get('fingerprint') and data['asset'].get('fingerprint') != row['fingerprint']:
            issue('ANALYSIS_FINGERPRINT_REQUIRED', where, '严格审看关联需携带匹配当前库存的素材 fingerprint，防止复用旧结论。')
        sid = clip.get('segment_id', clip.get('analysis_segment_id'))
        segment = data['segments'].get(sid) if isinstance(sid, str) else None
        if segment is None:
            issue('ANALYSIS_SEGMENT_REF', where, '入选镜头需用 segment_id 引用该素材的已审片段。'); continue
        if segment.get('decision') in ('skip', 'rejected'):
            issue('ANALYSIS_SEGMENT_REJECTED', where, '入选镜头引用了跳过片段，请复核并更新分析。')
        if row.get('kind') == 'image':
            if a != 0 or not (data['frame_times'] or data['playback_ranges']):
                issue('ANALYSIS_SELECTION_COVERAGE', where, '入选图片需记录 time=0 的实际审看证据。')
            continue
        if segment['source_in'] > a+.002 or segment['source_out'] < b-.002:
            issue('ANALYSIS_SEGMENT_RANGE', where, '镜头源区间超出所引用分析片段。')
        if not covered(a, b, data['ranges']):
            issue('ANALYSIS_SELECTION_COVERAGE', where, '入选区间未被回放或首尾间隔不超过1秒的已查看帧覆盖；补看后记录。')
        elif not covered(a, b, data['playback_ranges']):
            warnings.append(f'{where} 仅有密集抽帧审看记录；连续运动、精确切点与声音仍需实际回放复核。')
    for ident, a, b, where in valid_wanted:
        data = index.get(ident)
        if lookup[ident].get('kind') != 'image' and (not data or not covered(a, b, data['ranges'])):
            issue('MUST_KEEP_RANGE_UNREVIEWED', where, '必留源区间尚未完成可核对的审看覆盖。')

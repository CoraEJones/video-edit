"""Shared chat/wizard request validation and explicit, content-bound confirmation.

This module never extracts meaning from a chat, chooses a user's source folder,
opens a window or starts processing. The host asks the returned missing questions,
shows ``summary_lines`` and calls ``confirm_request`` only after an actual reply.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re

from .common import EditError, IMAGE_EXTS, VIDEO_EXTS, safe_name, resolve_path


# These are visible recommendations, not answers inferred from an incomplete prompt.
DEFAULTS = {
    'delivery_mode': 'mp4', 'target_seconds': 90, 'category': '旅行',
    'theme': '由助手推荐', 'rhythm': '有电影感',
    'subtitle_language': '简体中文', 'subtitles': True,
    'voiceover': False, 'voice_gender': '由助手推荐',
    'aspect': '横屏 16:9', 'music': '自动配乐', 'music_file': None,
    'must_keep': '', 'must_keep_files': [], 'context': '', 'name': '我的回忆',
    'text_style': '自动搭配', 'title_mode': 'art_preferred', 'audio_policy': 'strict',
    'opening_style': 'highlight_reveal', 'ending_style': 'slow_echo',
    'allow_select': True, 'duration_policy': 'soft', 'quality_policy': 'preserve_source',
}

FIELD_LABELS = {
    'media_dir': '素材文件夹', 'output_dir': '输出位置', 'delivery_mode': '交付方式',
    'name': '作品名称', 'target_seconds': '目标时长', 'category': '素材类型',
    'theme': '故事主题', 'rhythm': '风格与节奏', 'aspect': '横屏／竖屏／方形',
    'subtitles': '是否添加字幕', 'subtitle_language': '字幕语言',
    'voiceover': '是否配音', 'voice_gender': '配音声音偏好',
    'music': '音乐方式', 'music_file': '自选音乐文件', 'context': '人物与故事背景',
    'must_keep': '必留或不要的内容', 'must_keep_files': '必留素材文件',
    'text_style': '文字风格', 'title_mode': '是否接受艺术字图片',
    'audio_policy': '原声保留与审核要求', 'opening_style': '片头偏好',
    'ending_style': '结尾偏好',
}

REQUIRED_FIELDS = (
    'media_dir', 'output_dir', 'delivery_mode', 'name', 'target_seconds', 'category',
    'theme', 'rhythm', 'aspect', 'subtitles', 'voiceover', 'music', 'context',
    'must_keep', 'must_keep_files', 'text_style', 'title_mode', 'audio_policy',
    'opening_style', 'ending_style',
)

CHOICE_LABELS = {
    'mp4': '只要 MP4 成片，无需剪映',
    'editable': 'MP4 成片＋剪映可编辑工程，需要本地剪映',
    'art_preferred': '艺术字优先；失败时使用可编辑字体排版',
    'fonts_only': '使用字体库字体，保留可编辑文字',
    'strict': '严格审核；不清楚就静音，变速原声静音',
    'key_speech_only': '仅保留审核清楚的关键讲话；变速原声静音',
    'mute_all': '全部原声静音',
    'highlight_reveal': '精彩快闪＋上下黑幕揭题，按素材调整',
    'photo_carousel': '照片／视频横向或竖向走马灯，按素材调整',
    'story_based': '由助手按故事推荐',
    'slow_echo': '结尾慢下来、呼应前文、无字留白',
    'linger': '保留有意味的长镜头与声音余韵',
}


def request_fingerprint(request):
    """Exclude UI/cache metadata only; all user-facing request content is bound."""
    metadata = {'confirmation', 'schema_version', 'custom_seconds', 'host', 'entry_mode',
                'inventory', 'inventory_path', 'analysis_dir', 'analysis_report'}
    if any(not isinstance(k, str) for k in request):
        raise EditError('REQUEST_FORMAT', '制作需求的字段名必须是字符串。')
    content = {k: v for k, v in request.items()
               if k not in metadata and not k.startswith('_')}
    try:
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EditError('REQUEST_FORMAT', '制作需求必须是有效的 JSON 数据。') from exc
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _placeholder(raw):
    normalized = raw.strip().replace('/', '\\').casefold().rstrip('\\')
    # A real user may actually own D:\旅行素材. Reject explicit placeholders,
    # while normal filesystem validation decides whether ordinary paths are real.
    return (bool(re.search(r'[<>]|\$\{|\{[^}]+\}', raw))
            or normalized in ('素材路径', '输出路径', '素材文件夹', 'path\\to\\media', '...'))


def _path_issue(field, raw, *, kind, must_exist):
    if not isinstance(raw, str) or not raw.strip():
        return {'field': field, 'path': raw, 'reason': '请提供实际路径。'}
    if _placeholder(raw):
        return {'field': field, 'path': raw, 'reason': '这是范例或占位路径，请选择实际位置。'}
    try:
        p = Path(os.path.expandvars(raw)).expanduser()
        if not p.is_absolute():
            return {'field': field, 'path': raw, 'reason': '请使用完整路径，避免相对目录指向错误位置。'}
        if must_exist and not p.exists():
            return {'field': field, 'path': raw, 'reason': '路径不存在，请重新选择。'}
        if p.exists() and not (p.is_dir() if kind == 'directory' else p.is_file()):
            return {'field': field, 'path': raw, 'reason': '需要文件夹。' if kind == 'directory' else '需要文件。'}
        if p.exists() and not os.access(p, os.R_OK):
            return {'field': field, 'path': raw, 'reason': '当前无法读取，请检查权限。'}
        if not p.exists():
            ancestor = next((a for a in p.parents if a.exists()), None)
            if ancestor is None or not ancestor.is_dir():
                return {'field': field, 'path': raw, 'reason': '输出所在磁盘或上级文件夹不存在。'}
    except (OSError, ValueError) as exc:
        return {'field': field, 'path': raw, 'reason': str(exc)}
    return None


def suggest_output(request, cfg=None):
    """Return a suggestion only. Do not insert it into a request or confirm it."""
    base = (cfg or {}).get('output_root')
    if not base:
        raw = request.get('media_dir')
        if not raw or _path_issue('media_dir', raw, kind='directory', must_exist=True):
            return None
        base = str(Path(os.path.expandvars(raw)).expanduser().parent / '剪辑成品')
    try:
        name = safe_name(request.get('name') or DEFAULTS['name'])
        return str(resolve_path(base) / (datetime.now().strftime('%Y%m%d-%H%M%S') + '_' + name))
    except (OSError, ValueError, EditError):
        return None


def summary_lines(request):
    """Human-readable confirmation card, including conditional choices and paths."""
    def value(field):
        v = request.get(field)
        if field == 'target_seconds' and v is None and field in request:
            return '由助手推荐'
        if v is True:
            return '开启'
        if v is False:
            return '关闭'
        if field in ('context', 'must_keep') and v == '':
            return '暂无补充'
        if field == 'must_keep_files' and isinstance(v, list):
            return '\n  '.join(str(p) for p in v) if v else '暂无指定'
        if field == 'target_seconds' and isinstance(v, (int, float)):
            return f'约 {v:g} 秒'
        return CHOICE_LABELS.get(v, v) if isinstance(v, str) else '尚未提供'

    fields = list(REQUIRED_FIELDS)
    if request.get('subtitles') is True:
        fields.insert(fields.index('subtitles') + 1, 'subtitle_language')
    if request.get('voiceover') is True:
        fields.insert(fields.index('voiceover') + 1, 'voice_gender')
    if request.get('music') == '使用我自己的音乐':
        fields.insert(fields.index('music') + 1, 'music_file')
    return [f'{FIELD_LABELS[field]}：{value(field)}' for field in fields]


def inspect_request(request, cfg=None):
    """Deterministically check completeness and confirmation without doing work.

    ``missing_fields`` are questions to ask, not permission to silently use DEFAULTS.
    ``confirmation_required`` remains true for partial and legacy requests. A host
    may read or validate an old plan; execution requires a current confirmed request.
    """
    if not isinstance(request, dict):
        raise EditError('REQUEST_FORMAT', '制作需求必须是 JSON 对象。')
    required = list(REQUIRED_FIELDS)
    if request.get('subtitles') is True:
        required.append('subtitle_language')
    if request.get('voiceover') is True:
        required.append('voice_gender')
    if request.get('music') == '使用我自己的音乐':
        required.append('music_file')
    allow_empty = {'context', 'must_keep', 'must_keep_files', 'target_seconds'}
    missing = [f for f in required if f not in request or
               (f not in allow_empty and (request[f] is None or request[f] == ''))]
    invalid, invalid_fields = [], []
    for field in ('media_dir', 'output_dir'):
        if field not in missing:
            error = _path_issue(field, request.get(field), kind='directory', must_exist=field == 'media_dir')
            if error:
                invalid.append(error)
    if 'music_file' in required and 'music_file' not in missing:
        error = _path_issue('music_file', request.get('music_file'), kind='file', must_exist=True)
        if error:
            invalid.append(error)
    keep = request.get('must_keep_files', [])
    if not isinstance(keep, list):
        invalid_fields.append({'field': 'must_keep_files', 'reason': '需要文件路径列表；无指定时使用空列表。'})
    else:
        for index, path in enumerate(keep):
            error = _path_issue(f'must_keep_files[{index}]', path, kind='file', must_exist=True)
            if error:
                invalid.append(error)
    for field in ('subtitles', 'voiceover'):
        if field not in missing and not isinstance(request.get(field), bool):
            invalid_fields.append({'field': field, 'reason': '需要明确开启或关闭（true / false）。'})
    delivery = request.get('delivery_mode')
    if 'delivery_mode' not in missing and delivery not in ('mp4', 'editable'):
        invalid_fields.append({'field': 'delivery_mode', 'reason': '请选择 mp4 或 editable。'})
    choices = {
        'title_mode': ('art_preferred', 'fonts_only'),
        'audio_policy': ('strict', 'key_speech_only', 'mute_all'),
        'opening_style': ('highlight_reveal', 'photo_carousel', 'story_based'),
        'ending_style': ('slow_echo', 'linger', 'story_based'),
        'music': ('自动配乐', '使用我自己的音乐', '只保留原声'),
    }
    for field, allowed in choices.items():
        if field not in missing and request.get(field) not in allowed:
            invalid_fields.append({'field': field, 'reason': '请选择支持的选项：' + '、'.join(allowed)})
    if request.get('music') == '只保留原声' and request.get('audio_policy') == 'mute_all':
        invalid_fields.append({'field': 'audio_policy', 'reason': '“只保留原声”与“全部原声静音”冲突，请选择配乐或允许审核后的原声。'})
    target = request.get('target_seconds')
    if 'target_seconds' not in missing and target is not None and (
            isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target) or not 10 <= target <= 7200):
        invalid_fields.append({'field': 'target_seconds', 'reason': '填写 10–7200 秒，或用 null 表示由助手推荐。'})
    for field in required:
        if field in missing or field in ('media_dir', 'output_dir', 'music_file', 'must_keep_files', 'target_seconds', 'subtitles', 'voiceover'):
            continue
        if not isinstance(request.get(field), str) or (field not in allow_empty and not request[field].strip()):
            invalid_fields.append({'field': field, 'reason': '请提供文字答案；不确定时可明确选择由助手推荐。'})
    if 'name' not in missing and isinstance(request.get('name'), str):
        try:
            safe_name(request['name'])
        except EditError as exc:
            invalid_fields.append({'field': 'name', 'reason': str(exc)})
    # Check a source sample is readable without probing, transcoding or writing.
    if 'media_dir' not in missing and not any(i['field'] == 'media_dir' for i in invalid):
        try:
            media = resolve_path(request['media_dir'])
            out = (resolve_path(request['output_dir'])
                   if 'output_dir' not in missing and not any(i['field'] == 'output_dir' for i in invalid) else None)
            if out is not None and out.is_relative_to(media):
                invalid.append({'field': 'output_dir', 'path': str(out),
                                'reason': '输出位置不能与原素材文件夹相同或位于其中，请选择素材文件夹之外的位置。'})
            for index, path in enumerate(keep if isinstance(keep, list) else []):
                if not isinstance(path, str) or any(i['field'] == f'must_keep_files[{index}]' for i in invalid):
                    continue
                if not resolve_path(path).is_relative_to(media):
                    invalid.append({'field': f'must_keep_files[{index}]', 'path': path,
                                    'reason': '必留文件需位于所选素材文件夹内，请先调整素材范围。'})
            candidate = next((p for p in media.rglob('*') if p.is_file() and p.suffix.lower() in VIDEO_EXTS | IMAGE_EXTS), None)
            if candidate is None:
                invalid.append({'field': 'media_dir', 'path': str(media), 'reason': '没有找到支持的视频或照片。'})
            else:
                with candidate.open('rb') as stream:
                    stream.read(1)
        except (OSError, ValueError) as exc:
            invalid.append({'field': 'media_dir', 'path': request['media_dir'], 'reason': '素材不可读取：' + str(exc)})
    fingerprint = request_fingerprint(request)
    confirmation = request.get('confirmation')
    confirmed = (isinstance(confirmation, dict) and confirmation.get('confirmed') is True
                 and confirmation.get('fingerprint') == fingerprint
                 and confirmation.get('method') in ('chat_explicit_reply', 'wizard_confirm_button'))
    complete = not missing and not invalid and not invalid_fields
    return {
        'ready': complete and confirmed, 'complete': complete,
        'missing_fields': missing, 'invalid_paths': invalid, 'invalid_fields': invalid_fields,
        'confirmation_required': not confirmed or not complete,
        'fingerprint': fingerprint, 'questions': [{'field': f, 'label': FIELD_LABELS[f]} for f in missing],
        'suggested_output_dir': suggest_output(request, cfg) if 'output_dir' in missing else None,
        'summary_lines': summary_lines(request), 'processing_started': False,
    }


def confirm_request(request, user_confirmed, *, method='chat_explicit_reply', cfg=None):
    """Record a real human reply; never infer approval from timeout or defaults.

    A CLI flag is only a receipt for an explicit human confirmation in the current
    conversation; an agent must not set it merely to get past this check.
    """
    result = deepcopy(request)
    result.pop('confirmation', None)
    if user_confirmed is not True:
        return result
    check = inspect_request(result, cfg)
    if not check['complete']:
        raise EditError('REQUEST_INCOMPLETE', '路径或需求尚未完整，请补问并重新展示制作确认单。', check)
    if method not in ('chat_explicit_reply', 'wizard_confirm_button'):
        raise EditError('CONFIRMATION_METHOD', '确认必须来自用户明确回复或向导确认按钮。')
    result['confirmation'] = {
        'confirmed': True, 'fingerprint': check['fingerprint'], 'method': method,
        'confirmed_at': datetime.now(timezone.utc).isoformat(),
    }
    return result


def require_confirmed_request(request, cfg=None):
    check = inspect_request(request, cfg)
    if not check['complete']:
        raise EditError('REQUEST_INCOMPLETE', '请补齐实际路径和剪辑需求，再向用户展示制作确认单。', check)
    if check['confirmation_required']:
        raise EditError('REQUEST_CONFIRMATION_REQUIRED', '尚未确认制作需求，或关键内容已改变；请重新展示汇总并等待用户明确确认。', check)
    return check


def require_delivery_request(request, output_dir, delivery_mode, cfg=None):
    """Reject an export destination/type different from the confirmed request."""
    check = require_confirmed_request(request, cfg)
    expected = resolve_path(request['output_dir'])
    actual = resolve_path(output_dir)
    if actual != expected or delivery_mode != request['delivery_mode']:
        raise EditError('DELIVERY_CONFIRMATION_MISMATCH',
                        '交付位置或交付方式与已确认方案不同，请先更新需求并重新确认。',
                        {'confirmed_output_dir': str(expected), 'actual_output_dir': str(actual),
                         'confirmed_delivery_mode': request['delivery_mode'], 'actual_delivery_mode': delivery_mode})
    return check


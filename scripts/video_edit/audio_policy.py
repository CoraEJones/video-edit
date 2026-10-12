"""Opt-in original sound: actual listening is an editorial prerequisite."""
from __future__ import annotations
import math
from pathlib import Path
from .common import EditError, run


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def original_audio_window(shot, total, source_duration):
    """Source seconds and timeline seconds coincide only at normal speed."""
    lead = min(max(0, shot.get('audio_lead', 0)), shot['start'], shot['source_in'])
    tail = min(max(0, shot.get('audio_tail', 0)),
               max(0, total - shot['start'] - shot['duration']),
               max(0, source_duration - shot['source_in'] - shot['duration']))
    return {'source_start': shot['source_in'] - lead,
            'source_end': shot['source_in'] + shot['duration'] + tail,
            'start': shot['start'] - lead, 'duration': shot['duration'] + lead + tail}


def denoise_filter(settings):
    """A small, fixed filter surface; never accept raw FFmpeg expressions."""
    if settings is None:
        return None
    if not isinstance(settings, dict) or set(settings) - {'filter', 'noise_reduction', 'evidence'}:
        raise EditError('ORIGINAL_AUDIO_DENOISE', '降噪只接受 filter、noise_reduction 和试听 evidence。')
    nr = settings.get('noise_reduction', 8)
    if settings.get('filter') != 'afftdn' or not _number(nr) or not 6 <= nr <= 12:
        raise EditError('ORIGINAL_AUDIO_DENOISE', '仅支持轻度 afftdn，noise_reduction 为 6 到 12 dB。')
    return f'afftdn=nr={nr:g}'


def validate_original_audio(plan, rows, issue):
    """Validate declared evidence, not whether a human actually listened.

    issue has the plan validator's (code, where, message) signature. Missing
    audio_gain means silence, including older plans; positive legacy gains
    require fresh review instead of an invented approval.
    """
    lookup = {r['id']: r for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str)}
    policy = plan.get('request', {}).get('audio_policy', 'strict')
    for group in ('shots', 'panels'):
        for i, shot in enumerate(plan.get(group, [])):
            where = f'{group}[{i}]'
            gain = shot.get('audio_gain', 0)
            if not _number(gain) or not 0 <= gain <= 2:
                issue('ORIGINAL_AUDIO_GAIN', where + '.audio_gain', '原声音量需要 0 到 2 的有限数值；缺省为静音。')
                continue
            if 'important_speech' in shot and not isinstance(shot['important_speech'], bool):
                issue('ORIGINAL_AUDIO_REVIEW', where + '.important_speech', 'important_speech 需要布尔值。')
            if gain == 0:
                continue
            if policy == 'mute_all':
                issue('ORIGINAL_AUDIO_DISABLED', where, '用户选择全部原声静音，请将 audio_gain 设为 0。')
                continue
            if group == 'panels' or str(shot.get('purpose', '')).startswith('panels_'):
                issue('ORIGINAL_AUDIO_PANEL', where, '分屏不输出原声；需要关键讲话时安排正常速度主轨镜头。')
                continue
            speed = shot.get('speed')
            if not _number(speed) or abs(speed - 1) > 1e-8:
                issue('ORIGINAL_AUDIO_SPEED', where, '变速镜头原声必须静音；关键讲话另用正常速度镜头承接。')
                continue
            source = lookup.get(shot.get('id'))
            if not source:
                issue('ORIGINAL_AUDIO_SOURCE', where, '找不到原声音源素材。')
                continue
            if source.get('kind') == 'image' or not source.get('has_audio', bool(source.get('audio'))):
                issue('ORIGINAL_AUDIO_SOURCE', where, '所选素材没有可保留的原音轨。')
                continue
            review = shot.get('audio_review')
            if not isinstance(review, dict) or review.get('status') != 'approved':
                issue('ORIGINAL_AUDIO_REVIEW_REQUIRED', where + '.audio_review', '非零原声需实际试听后填写 approved 审核记录；旧计划也须重审，或将 audio_gain 设为 0。')
                continue
            if review.get('quality') != 'clear':
                issue('ORIGINAL_AUDIO_QUALITY', where + '.audio_review', '原声必须已听审为清晰可用；噪声、爆音、含混或未确定时静音。')
            if review.get('purpose') not in ('key_speech', 'story_sound'):
                issue('ORIGINAL_AUDIO_PURPOSE', where + '.audio_review', '仅保留清晰关键讲话 key_speech 或明确选中的优质叙事同期声 story_sound。')
            if policy == 'key_speech_only' and review.get('purpose') != 'key_speech':
                issue('ORIGINAL_AUDIO_SPEECH_ONLY', where + '.audio_review', '用户选择仅保留关键讲话，不能额外保留叙事环境原声。')
            for field in ('evidence', 'reason'):
                if not isinstance(review.get(field), str) or not review[field].strip():
                    issue('ORIGINAL_AUDIO_REVIEW', where + '.audio_review.' + field, '填写实际试听文件/时码与结论，以及该声音的故事价值，不能自动伪造审核。')
            for field in ('source_start', 'source_end'):
                if not _number(review.get(field)):
                    issue('ORIGINAL_AUDIO_REVIEW_RANGE', where + '.audio_review.' + field, '试听源区间需要有限秒数。')
            numbers = [shot.get(k, 0) for k in ('start', 'duration', 'source_in', 'audio_lead', 'audio_tail')]
            if all(_number(v) and v >= 0 for v in numbers) and _number(source.get('duration')) and _number(plan.get('duration')):
                window = original_audio_window(shot, plan['duration'], source['duration'])
                a, b = review.get('source_start'), review.get('source_end')
                if _number(a) and _number(b) and (a < 0 or b <= a or b > source['duration'] + .002 or
                        a > window['source_start'] + .002 or b < window['source_end'] - .002):
                    issue('ORIGINAL_AUDIO_REVIEW_RANGE', where + '.audio_review', '实际试听源区间须覆盖保留声音及 J/L 前后延伸，且不可超过原音轨。')
            else:
                issue('ORIGINAL_AUDIO_REVIEW_RANGE', where, '无法计算有效原声区间；先修正镜头及素材时间。')
            if 'denoise' in review:
                try:
                    denoise_filter(review['denoise'])
                    if not isinstance(review['denoise'], dict) or not isinstance(review['denoise'].get('evidence'), str) or not review['denoise']['evidence'].strip():
                        issue('ORIGINAL_AUDIO_DENOISE_REVIEW', where + '.audio_review.denoise', '必须先生成并实际试听降噪结果，再记录该文件和听审结论。')
                except EditError as exc:
                    issue(exc.code, where + '.audio_review.denoise', str(exc))


def render_review_audio(source, output, source_start, source_end, cfg, denoise=None):
    """Render a PCM listening sample. This does not approve its sound quality."""
    if not all(_number(v) for v in (source_start, source_end)) or not 0 <= source_start < source_end:
        raise EditError('ORIGINAL_AUDIO_REVIEW_RANGE', '试听样本需要有效的源入点和出点。')
    source, output = Path(source), Path(output)
    if not source.is_file() or source.resolve() == output.resolve() or output.suffix.lower() != '.wav':
        raise EditError('ORIGINAL_AUDIO_SAMPLE', '需现有声音源和不同的 WAV 输出路径，不能覆盖原片。')
    effect = denoise_filter(denoise)
    # The native preparation uses the same 48 kHz / stereo / 16-bit PCM base.
    filters = ['aresample=48000', 'aformat=sample_fmts=s16:channel_layouts=stereo']
    if effect:
        filters.append(effect)
    output.parent.mkdir(parents=True, exist_ok=True)
    run([cfg['ffmpeg'], '-v', 'error', '-i', source, '-ss', source_start,
         '-t', source_end - source_start, '-vn', '-af', ','.join(filters),
         '-ac', '2', '-ar', 48000, '-c:a', 'pcm_s16le', '-y', output])
    import wave
    with wave.open(str(output), 'rb') as wav:
        duration = wav.getnframes() / wav.getframerate()
        params, samples = wav.getparams(), wav.readframes(wav.getnframes())
    if duration + .002 < source_end - source_start:
        raise EditError('ORIGINAL_AUDIO_SAMPLE_SHORT', '试听样本短于要求区间，请核对原音轨时长。')
    # Jianying's material probe uses milliseconds. Pad only the final fraction
    # so it cannot shorten the selected ending or reject a frame-aligned range.
    required = math.ceil((source_end - source_start) * 1000) * 48
    if params.nframes < required:
        with wave.open(str(output), 'wb') as wav:
            wav.setparams(params)
            wav.writeframes(samples + b'\x00' * ((required - params.nframes) * 4))
    return {'path': str(output.resolve()), 'source_start': source_start, 'source_end': source_end,
            'filter_applied': effect, 'codec': 'pcm_s16le', 'status': 'needs_listening',
            'note': '处理完成不代表音质合格；实际试听后才能填写 audio_review。'}

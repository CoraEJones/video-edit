"""Explicit editorial music/ambience/SFX; no automatic library guessing."""
from __future__ import annotations
import math
from pathlib import Path
from .common import EditError, probe, run, sha256


def validate_layers(plan, cfg, issue, inspect_files=True):
    layers = plan.get('audio_layers', [])
    if not isinstance(layers, list) or any(not isinstance(x, dict) for x in layers):
        issue('AUDIO_LAYERS_FORMAT', 'audio_layers', '需要音轨对象数组')
        return
    def number(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    for i, layer in enumerate(layers):
        where = f'audio_layers[{i}]'
        allowed = {'kind', 'path', 'start', 'duration', 'source_in', 'gain', 'fade_in',
                   'fade_out', 'loop', 'source_note', 'license', 'sha256'}
        unknown = set(layer) - allowed
        if unknown:
            issue('AUDIO_FIELD_UNSUPPORTED', where, '不支持的音轨字段：' + ', '.join(sorted(unknown)))
        if layer.get('kind') not in ('music', 'ambience', 'sfx'):
            issue('AUDIO_KIND', where, 'kind 需要 music、ambience 或 sfx')
        path = layer.get('path')
        if not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file():
            issue('AUDIO_FILE', where, 'path 需要存在的音频绝对路径')
            continue
        values = {k: layer.get(k, default) for k, default in
                  [('start', None), ('duration', None), ('source_in', 0), ('gain', .25),
                   ('fade_in', .2), ('fade_out', .3)]}
        if any(not number(v) for v in values.values()):
            issue('AUDIO_NUMBER', where, '音轨时间、音量和淡化需要有限数值')
            continue
        a, d, src = values['start'], values['duration'], values['source_in']
        if a < 0 or d <= 0 or src < 0 or a + d > plan['duration'] + .00002:
            issue('AUDIO_TIME', where, '音轨区间必须位于成片内，源入点非负')
        if not 0 <= values['gain'] <= 2:
            issue('AUDIO_GAIN', where, 'gain 需要 0 到 2 的线性增益')
        if any(values[k] < 0 or values[k] > d for k in ('fade_in', 'fade_out')):
            issue('AUDIO_FADE', where, '淡化不能为负或超过音轨时长')
        if not isinstance(layer.get('loop', False), bool):
            issue('AUDIO_LOOP', where, 'loop 需要布尔值')
        if not isinstance(layer.get('source_note'), str) or not layer['source_note'].strip():
            issue('AUDIO_PROVENANCE', where, '填写声音来源与用途；库音不能冒充现场')
        if plan.get('request', {}).get('music') == '只保留原声':
            issue('ORIGINAL_ONLY', where, '用户选择只保留原声时清空所有添加音轨')
        if inspect_files:
            try:
                if layer.get('sha256') is not None and layer['sha256'] != sha256(path):
                    issue('AUDIO_SOURCE_CHANGED', where, '音频与已审看/入库哈希不一致，请重新核实来源')
                info = probe(path, cfg)
                if not info.get('has_audio'):
                    issue('AUDIO_STREAM', where, '文件没有音频流')
                if src >= info['duration'] or (not layer.get('loop') and src + d > info['duration'] + .002):
                    issue('AUDIO_SOURCE_OVERFLOW', where, '声音源区间超出时长；需要循环时明确设置 loop')
            except Exception as exc:
                issue('AUDIO_PROBE', where, str(exc))


def prepare_layers(plan, audio, cfg, add_event):
    """Normalize only audio; keep a verified original for portability/provenance."""
    import shutil
    import wave
    reports = []
    for i, layer in enumerate(plan.get('audio_layers', [])):
        source = Path(layer['path'])
        original = audio / f'库音原件_{i:03d}{source.suffix}'
        shutil.copy2(source, original)
        digest = sha256(original)
        if digest != sha256(source):
            raise EditError('AUDIO_COPY', '附加声音复制校验失败')
        dest = audio / f'附加音轨_{i:03d}.wav'
        args = [cfg['ffmpeg'], '-v', 'error']
        if layer.get('loop'):
            args += ['-stream_loop', '-1']
        args += ['-i', source, '-ss', layer.get('source_in', 0), '-t', layer['duration'],
                 '-vn', '-ac', '2', '-ar', 48000, '-c:a', 'pcm_s16le', '-y', dest]
        run(args)
        with wave.open(str(dest), 'rb') as wav:
            actual = wav.getnframes() / wav.getframerate()
            params, samples = wav.getparams(), wav.readframes(wav.getnframes())
        if actual + .002 < layer['duration']:
            raise EditError('AUDIO_TOO_SHORT', '附加音轨解码长度不足，不能用静音冒充完成')
        # The native library probes duration at millisecond precision. Preserve
        # the exact event duration but pad its backing PCM to the next millisecond.
        required_samples = math.ceil(layer['duration'] * 1000) * 48
        if params.nframes < required_samples:
            with wave.open(str(dest), 'wb') as wav:
                wav.setparams(params)
                wav.writeframes(samples + b'\x00' * ((required_samples - params.nframes) * 4))
        e = add_event(dest, layer['start'], layer['duration'], gain=layer.get('gain', .25),
                      track=layer['kind'], fi=layer.get('fade_in', .2), fo=layer.get('fade_out', .3))
        reports.append({'index': i, 'kind': layer['kind'], 'original': str(original), 'sha256': digest,
                        'source_in': layer.get('source_in', 0), 'loop': layer.get('loop', False),
                        'source_note': layer['source_note'], 'license': layer.get('license'),
                        'start': e['start'], 'duration': e['duration']})
    return reports


def duck_background(events, speech_spans):
    """Keys are local to each event, matching preview and native automation."""
    import numpy as np
    for e in events:
        if e['track'] not in ('music', 'ambience', 'sfx'):
            continue
        local = np.unique(np.r_[np.arange(0, e['duration'], .05), e['duration']])
        ts = local + e['start']
        gains = np.ones(len(ts))
        for a, b in speech_spans:
            duck = np.minimum(np.clip((ts - (a - .2)) / .2, 0, 1),
                              np.clip(((b + .3) - ts) / .3, 0, 1))
            gains = np.minimum(gains, 1 - .73 * duck)
        e['keys'] = [[round(float(local[i]), 6), round(float(gains[i]), 4)]
                     for i in range(len(local)) if i == 0 or i == len(local) - 1
                     or abs(gains[i] - gains[i-1]) > .0001
                     or (i+1 < len(local) and abs(gains[i+1] - gains[i]) > .0001)]

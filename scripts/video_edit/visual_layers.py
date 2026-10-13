"""Editable foreground layers shared by the native and FFmpeg backends."""
from __future__ import annotations
import math


FIELDS = {'id', 'start', 'duration', 'source_in', 'speed', 'x', 'y', 'scale', 'keyframes', 'purpose',
          'segment_id', 'analysis_segment_id', 'color'}


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize(layer):
    return {'source_in': 0, 'speed': 1, 'x': 0, 'y': 0, 'scale': 1, **layer}


def normalized_layers(plan):
    return [normalize(layer) for layer in plan.get('visual_layers', [])]


def validate_visual_layers(plan, lookup, selected, issue):
    fps = plan['fps']
    for i, raw in enumerate(plan.get('visual_layers', [])):
        where = f'visual_layers[{i}]'
        unknown = set(raw) - FIELDS
        if unknown:
            issue('VISUAL_FIELD', where, '不支持的视觉字段：' + ', '.join(sorted(unknown)))
        layer = normalize(raw)
        ident = layer.get('id')
        row = lookup.get(ident) if isinstance(ident, str) else None
        if not row:
            issue('UNKNOWN_ASSET', where + '.id', '图层必须引用素材清单中的真实图片或视频编号')
        else:
            selected.add(ident)
            if row.get('kind') not in ('image', 'video'):
                issue('VISUAL_KIND', where, '视觉图层只接受 image 或 video 素材')
        valid_numbers = True
        for key in ('start', 'duration', 'source_in', 'speed', 'x', 'y', 'scale'):
            if not finite(layer.get(key)):
                valid_numbers = False
                issue('VISUAL_NUMBER', where + '.' + key, '需要有限数值')
        if not valid_numbers:
            continue
        a, d, src, speed = (layer[k] for k in ('start', 'duration', 'source_in', 'speed'))
        if a < 0 or d <= 0 or a + d > plan['duration'] + .00002:
            issue('VISUAL_TIME', where, '图层必须完全位于时间线内且时长为正')
        for key in ('start', 'duration'):
            if abs(layer[key] * fps - round(layer[key] * fps)) > .002:
                issue('VISUAL_FRAME', where + '.' + key, '图层起点和时长必须对齐项目帧率')
        if src < 0 or not .25 <= speed <= 4:
            issue('VISUAL_SOURCE', where, '素材入点必须非负，视频速度必须为 0.25–4')
        if row:
            if row.get('kind') == 'image' and (src != 0 or speed != 1):
                issue('VISUAL_IMAGE_RANGE', where, '照片的 source_in 必须为 0，speed 必须为 1')
            elif row.get('kind') == 'video' and src + d * speed > row['duration'] + .002:
                issue('SOURCE_OVERFLOW', where, '视觉图层超出源视频时长')
        if not .01 <= layer['scale'] <= 4:
            issue('VISUAL_SCALE', where + '.scale', 'scale 为相对适配画布后大小，范围 0.01–4')
        for axis in ('x', 'y'):
            if not -4 <= layer[axis] <= 4:
                issue('VISUAL_POSITION', where + '.' + axis, '位置坐标范围为 -4–4')
        if 'purpose' in layer and not isinstance(layer['purpose'], str):
            issue('VISUAL_PURPOSE', where + '.purpose', '用途说明必须为文字')
        if 'keyframes' not in layer:
            continue
        keys = layer['keyframes']
        if not isinstance(keys, list) or not keys or any(not isinstance(k, dict) for k in keys):
            issue('VISUAL_KEYFRAMES', where, 'keyframes 需要非空对象数组；静态图层省略此字段')
            continue
        previous = -1
        for j, key in enumerate(keys):
            at = f'{where}.keyframes[{j}]'
            if set(key) != {'time', 'x', 'y'} or any(not finite(key.get(k)) for k in ('time', 'x', 'y')):
                issue('VISUAL_KEYFRAME', at, '每个关键帧恰好需要 time、x、y 三个有限数值')
                continue
            t = key['time']
            if t <= previous or t < 0 or t > max(0, d - 1 / fps) + .00002:
                issue('VISUAL_KEYFRAME_TIME', at, '关键帧必须递增，位于首帧到最后一个可见帧之间')
            if abs(t * fps - round(t * fps)) > .002:
                issue('VISUAL_KEYFRAME_FRAME', at, '关键帧须对齐项目帧率')
            if any(not -4 <= key[axis] <= 4 for axis in ('x', 'y')):
                issue('VISUAL_POSITION', at, '位置坐标范围为 -4–4')
            previous = t
        if finite(keys[0].get('time')) and abs(keys[0]['time']) > .00002:
            issue('VISUAL_KEYFRAME_START', where, '第一个关键帧 time 必须为 0')
        if finite(keys[-1].get('time')) and abs(keys[-1]['time'] - max(0, d - 1 / fps)) > .00002:
            issue('VISUAL_KEYFRAME_END', where, '末关键帧必须位于 duration - 1/fps，确保最后可见帧到达终点')


def initial_position(layer):
    return layer['keyframes'][0] if layer.get('keyframes') else layer


def position_expression(layer, axis, time='t'):
    """FFmpeg expression: the same piecewise-linear points as native keyframes."""
    keys = layer.get('keyframes')
    if not keys:
        return f'{layer[axis]:.12g}'
    local = f'({time}-{layer["start"]:.12g})'
    expr = f'{keys[-1][axis]:.12g}'
    for left, right in reversed(list(zip(keys, keys[1:]))):
        value = (f'{left[axis]:.12g}+({right[axis]-left[axis]:.12g})*'
                 f'clip(({local}-{left["time"]:.12g})/{right["time"]-left["time"]:.12g},0,1)')
        expr = f'if(lt({local},{right["time"]:.12g}),{value},{expr})'
    return expr

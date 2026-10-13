"""Export typed technique layers to an isolated, editable Jianying draft.

This backend distinguishes native parameters, generated source assets, and a
whole-composition fallback. Codec round-trip is not editor/UI verification.
No preset IDs are invented and no user draft registry is read or modified.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import tempfile

from .common import ROOT, EditError, probe, read, run, safe_name, sha256, write
from .technique_spec import TRANSFORMS, resolve, validate


MIX_NAMES = {'screen': '滤色', 'multiply': '正片叠底',
             'lighten': '变亮', 'darken': '变暗'}
MASK_NAMES = {'rect': ('矩形', 'rect'), 'ellipse': ('圆形', 'circle'),
              'linear': ('线性', 'linear')}


def _us(value):
    return round(value * 1_000_000)


def _rgb(value):
    return tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))


def resource_for(kind, cfg, *, effect_id=None):
    """Find an actual cached effect; do not download or guess resource IDs."""
    candidates = []
    configured = cfg.get('native_mask_dirs', {}).get(kind)
    if configured:
        candidates.append(Path(configured))
    if kind == 'rect' and cfg.get('rectangle_mask_dir'):
        candidates.append(Path(cfg['rectangle_mask_dir']))
    root = Path(cfg['jianying_user_data']) / 'Cache/effect' if cfg.get('jianying_user_data') else None
    if root and root.is_dir():
        patterns = [f'{effect_id}/*/config.json'] if effect_id else ['*/*/config.json']
        for pattern in patterns:
            candidates.extend(p.parent for p in sorted(root.glob(pattern)))
    expected = MASK_NAMES.get(kind, (None, None))[1]
    for folder in candidates:
        try:
            conf = read(folder / 'config.json')
            if expected and conf.get('name') != expected:
                continue
            if not isinstance(conf, dict) or not conf.get('effect'):
                continue
            if expected and not (folder / 'amazingfeature').is_dir():
                continue
            return folder.resolve()
        except (OSError, EditError, ValueError):
            continue
    return None


def _mix_resource(mode, cfg):
    if mode not in MIX_NAMES:
        return None
    import pyJianYingDraft as draft
    meta = getattr(draft.MixModeType, MIX_NAMES[mode]).value
    return resource_for('mix', cfg, effect_id=meta.effect_id)


def capabilities(spec, base, cfg, *, inspect_files=True):
    """Typed validation plus precise native/derived routing, without writing."""
    checked = validate(spec, base, cfg, inspect_files=inspect_files)
    if not checked['valid']:
        return dict(checked, native=False, layers=[])
    results = []
    for layer in spec['layers']:
        ident = layer['id']; unsupported = []; approximations = []; generated = []
        source = layer['source']; kind = source.get('kind', 'asset')
        metadata=checked.get('assets',{}).get(ident,{}).get('metadata',{})
        if metadata.get('sample_aspect_ratio') not in (None,'','N/A','0:1','1:1','1/1'):
            unsupported.append('sample_aspect_ratio: normalize display geometry into a transparent source before native transforms')
        if source.get('loop'):
            unsupported.append('loop: native seamless loop/source mapping not implemented')
        for key in ('speed_curve', 'reverse', 'key', 'color', 'crop'):
            if key in layer and layer[key] is not None:
                unsupported.append(key + ': no calibrated native mapping in this backend')
        if 'freeze_at' in layer:
            generated.append('freeze_at: decoded PNG source; the image hold is editable, the original source-time freeze is not a native parameter')
        if kind == 'solid':
            generated.append('solid: generated RGBA PNG source')
        if kind == 'text':
            approximations.append('text: editable font size/stroke; size=font_size_px/6 and relative stroke are library-unit mappings, not a pixel-equivalence guarantee')
            if source.get('glow_radius_px', 0) and source.get('glow_opacity', .6):
                unsupported.append('glow_radius_px: no calibrated native glow implementation')
            if layer.get('mask') or layer.get('blend', 'normal') != 'normal':
                unsupported.append('text masks/mix: TextSegment has no matching video-mask/mix API')
            if any('opacity' in key for key in layer.get('keyframes', [])) or layer.get('fade_in') or layer.get('fade_out'):
                unsupported.append('text alpha animation: library documents KFTypeAlpha only for video; not claimed native')
        mask = layer.get('mask')
        if mask:
            typ = mask['type']
            if typ not in MASK_NAMES:
                unsupported.append('mask.' + typ + ': no validated matching resource/parameter route')
            elif not resource_for(typ, cfg):
                unsupported.append('mask.' + typ + ': required actual local mask resource is missing')
            if mask.get('feather_px', 0):
                unsupported.append('feather_px: pixel feather does not have a calibrated Jianying 0..100 mapping')
            if typ == 'linear':
                if isinstance(mask.get('progress', 1), list):
                    unsupported.append('linear mask progress animation: no validated mask keyframe API')
                else:
                    approximations.append('linear mask: geometry translated to native line center/rotation; polarity needs editor visual verification')
        blend = layer.get('blend', 'normal')
        if blend != 'normal':
            if blend not in MIX_NAMES:
                unsupported.append('blend.' + blend + ': no matching MixModeType')
            elif not _mix_resource(blend, cfg):
                unsupported.append('blend.' + blend + ': API enum exists but its actual effect cache is missing')
            else:
                approximations.append('blend: native resource-backed mix; matching encoded-RGB math needs editor pixel comparison')
        if layer.get('easing') == 'smoothstep':
            approximations.append('smoothstep: sampled at project frames into editable linear keyframes; no native Bezier curve claim')
        results.append({'id': ident, 'native': not unsupported, 'unsupported': unsupported,
                        'approximations': approximations, 'generated_sources': generated})
    return dict(checked, native=all(x['native'] for x in results), layers=results,
                ui_verified=False, audio='silent; original audio remains subject to the main workflow review')


def transform_samples(layer, fps, duration):
    """Sample typed output-time transforms; preserve visible CFR values.

    Opacity combines the typed alpha curve and independent fade multipliers.
    Smoothstep/fade products are sampled each project frame because the library
    only provides linear interpolation. Values remain editable keyframes.
    """
    keys = layer.get('keyframes') or []
    states = []
    state = {name: layer.get(name, default) for name, (_, _, default) in TRANSFORMS.items()}
    for key in keys:
        state = dict(state, **{k: v for k, v in key.items() if k != 'time'})
        states.append((key['time'], state.copy()))
    def value(name, t):
        default = layer.get(name, TRANSFORMS[name][2])
        if not states:
            return default
        if t <= states[0][0]:
            return states[0][1][name]
        for (a, va), (b, vb) in zip(states, states[1:]):
            if t <= b:
                q = (t - a) / (b - a)
                if layer.get('easing', 'linear') == 'smoothstep':
                    q = q * q * (3 - 2 * q)
                return va[name] + (vb[name] - va[name]) * q
        return states[-1][1][name]
    count = round(duration * fps)
    out = []
    for frame in range(count):
        t = frame / fps
        row = {'time': t, **{name: value(name, t) for name in TRANSFORMS}}
        if layer.get('fade_in', 0):
            row['opacity'] *= min(1, t / layer['fade_in'])
        if layer.get('fade_out', 0):
            row['opacity'] *= min(1, max(0, (duration - t) / layer['fade_out']))
        out.append(row)
    return out


def _copy_verified(source, dest, mappings, resources, kind):
    source = Path(source).resolve(); dest.parent.mkdir(parents=True, exist_ok=True)
    before = sha256(source)
    shutil.copy2(source, dest)
    if sha256(dest) != before or sha256(source) != before:
        raise EditError('SOURCE_CHANGED', '素材复制期间发生变化。', {'path': str(source)})
    resources.append({'kind': kind, 'source': str(source), 'path': str(dest), 'sha256': before})
    mappings[str(source)] = str(dest)
    return dest


def _package_spec(spec, base, folder, cfg):
    local = deepcopy(spec); resources = []; mappings = {}; font_defaults = {}
    def copy(path, kind):
        source = resolve(path, base)
        key = str(source)
        if key in mappings:
            return mappings[key]
        dest = folder / 'assets' / kind / f'{len(resources):03d}{source.suffix.lower()}'
        return str(_copy_verified(source, dest, mappings, resources, kind))
    for layer in local['layers']:
        source = layer['source']; kind = source.get('kind', 'asset')
        if kind == 'asset':
            source['path'] = copy(source['path'], 'originals')
        if kind == 'text':
            source['font_path'] = copy(source.get('font_path') or cfg['font_path'], 'fonts')
            font_defaults[layer['id']] = source['font_path']
        mask = layer.get('mask', {})
        if mask.get('type') == 'asset':
            mask['path'] = copy(mask['path'], 'originals')
        if mask.get('type') == 'text':
            mask['font_path'] = copy(mask.get('font_path') or cfg['font_path'], 'fonts')
    return local, resources, font_defaults


def _native_mask(segment, layer, canvas, cfg, resource_paths):
    import pyJianYingDraft as draft
    mask = layer['mask']; typ = mask['type']
    native_type = getattr(draft.MaskType, MASK_NAMES[typ][0])
    w, h = canvas['width'], canvas['height']
    sw, sh = segment.material_size
    fit = min(w / sw, h / sh)
    if typ == 'linear':
        angle = math.radians(mask.get('rotation', 0))
        extent = abs(w * math.cos(angle)) + abs(h * math.sin(angle))
        distance = (mask.get('progress', 1) - .5) * extent
        # Native line boundary is orthogonal to its rotation. This structural
        # mapping is explicitly listed as requiring editor polarity comparison.
        segment.add_mask(native_type, center_x=distance * math.cos(angle) / fit,
                         center_y=-distance * math.sin(angle) / fit,
                         rotation=mask.get('rotation', 0) + 90,
                         invert=mask.get('invert', False), feather=0)
    else:
        segment.add_mask(native_type, center_x=mask.get('x', 0) * w / (2 * fit),
                         center_y=mask.get('y', 0) * h / (2 * fit),
                         size=mask.get('height', 1) * h / (sh * fit),
                         rotation=mask.get('rotation', 0), invert=mask.get('invert', False),
                         feather=0, **({'rect_width': mask.get('width', 1) * w / (sw * fit)} if typ == 'rect' else {}))
        # Mask.width/height are public geometry properties; circle resource
        # supports elliptical dimensions in the exported config structure.
        segment.mask.width = mask.get('width', 1) * w / (sw * fit)
        segment.mask.height = mask.get('height', 1) * h / (sh * fit)
    resource_paths[segment.mask.global_id] = resource_for(typ, cfg)


def export_native(spec, base, cfg, output, *, name='技巧原生测试', allow_derived=False):
    """Create a new standalone draft folder; never register or touch user drafts.

    Unsupported graphs raise before copying unless allow_derived=True. Local
    operations fall back to a transparent asset per layer, retaining native
    transforms/tracks. Only unsupported background-dependent mix collapses the
    composition. Baked operations are never labelled native editable effects.
    """
    report = capabilities(spec, base, cfg)
    if not report['valid']:
        raise EditError('INVALID_TECHNIQUE', '技巧参数检查未通过。', report)
    if not report['native'] and not allow_derived:
        raise EditError('NATIVE_TECHNIQUE_UNSUPPORTED', '部分技巧没有可靠的剪映原生参数映射。', report)
    from .native import codec, encode
    codec(cfg)  # Preflight actual isolated crypto before copying media.
    import pyJianYingDraft as draft
    from PIL import Image
    folder = Path(output).resolve()
    name = safe_name(name)
    if folder.exists():
        raise EditError('OUTPUT_EXISTS', '技巧工程输出必须是新目录。', {'path': str(folder)})
    folder.mkdir(parents=True)
    try:
        local, resources, _ = _package_spec(spec, base, folder, cfg)
        write(folder / 'technique-spec.json', local)
        canvas = local['canvas']; w, h, fps, total = [canvas[k] for k in ('width', 'height', 'fps', 'duration')]
        native_layers = deepcopy(local['layers']); partial = {}; derived_renders = {}
        # Blending requires the actual underlying composition. Its source
        # pixels cannot be pre-baked independently when the native mix route
        # is missing. Local masks/key/color/retiming/glow can be isolated.
        whole_baked = any(layer.get('blend', 'normal') != 'normal' and
            (layer['blend'] not in MIX_NAMES or not _mix_resource(layer['blend'], cfg))
            for layer in local['layers'])
        if not report['native'] and whole_baked:
            from .technique_spec import render
            derived = render(local, folder, cfg, folder / 'derived-composition')
            native_layers = [{'id': 'derived_composition', 'source': {'path': derived['output']},
                              'start': 0, 'duration': total}]
            report['derived_render'] = derived
            report['composition_fallback_reason'] = 'An unsupported mix depends on all underlying layers; independent transparent layer baking would change the result.'
        elif not report['native']:
            from .technique_spec import render
            by_id = {row['id']: row for row in report['layers']}
            for index, layer in enumerate(local['layers']):
                info = by_id[layer['id']]
                if info['native']:
                    continue
                isolated_layer = deepcopy(layer)
                isolated_layer['start'] = 0
                isolated_layer['duration'] = layer.get('duration', total)
                isolated_layer['blend'] = 'normal'
                for key in (*TRANSFORMS, 'keyframes', 'easing', 'fade_in', 'fade_out'):
                    isolated_layer.pop(key, None)
                isolated_canvas = dict(canvas, duration=isolated_layer['duration'], background_opacity=0)
                isolated = dict(local, canvas=isolated_canvas, layers=[isolated_layer])
                derived = render(isolated, folder, cfg, folder / f'derived-layer-{index:03d}')
                replacement = {key: deepcopy(layer[key]) for key in
                    ('id', 'start', 'duration', *TRANSFORMS, 'keyframes', 'easing', 'fade_in', 'fade_out', 'blend', 'purpose') if key in layer}
                replacement['source'] = {'path': derived['output']}
                native_layers[index] = replacement
                partial[layer['id']] = info['unsupported']
                derived_renders[layer['id']] = derived
            report['derived_layers'] = derived_renders
        font_by_id = {}; resource_paths = {}; track_reports = []
        def tr(start, duration): return draft.Timerange(_us(start), _us(duration))
        with tempfile.TemporaryDirectory(prefix='technique-native-') as temp:
            temp_root = Path(temp) / 'drafts'; temp_root.mkdir()
            df = draft.DraftFolder(str(temp_root), user_data_path=str(Path(temp) / 'User Data'))
            project = df.create_draft(name, w, h, fps=fps, allow_replace=False)
            # Explicit background source prevents gaps from shortening the
            # draft and makes transparent background intent inspectable.
            bg = folder / 'assets/graphics/background.png'; bg.parent.mkdir(parents=True, exist_ok=True)
            color = canvas.get('background', '#000000')
            alpha = round(canvas.get('background_opacity', 0) * 255)
            Image.new('RGBA', (w, h), tuple(round(c * 255) for c in _rgb(color)) + (alpha,)).save(bg)
            track = project.append_tracks([draft.TrackSpec(draft.TrackType.video, '画布背景')])[0]
            project.add_segment(draft.VideoSegment(str(bg), tr(0, total), volume=0), track=track)
            for index, layer in enumerate(native_layers):
                source = layer['source']; kind = source.get('kind', 'asset')
                start = layer.get('start', 0); length = layer.get('duration', total)
                initial = transform_samples(layer, fps, length)[0]
                clip = draft.ClipSettings(transform_x=initial['x'], transform_y=initial['y'],
                    scale_x=initial['scale'], scale_y=initial['scale'], rotation=initial['rotation'], alpha=initial['opacity'])
                if kind == 'text':
                    px = source.get('font_size_px', 64); stroke = source.get('stroke_px', 0)
                    # See capabilities(): these editable units are an explicit
                    # approximation, not a claim of matching PIL text metrics.
                    border = draft.TextBorder(color=_rgb(source.get('stroke_color', '#000000')),
                        width=min(100, stroke / px * 500)) if stroke else None
                    seg = draft.TextSegment(source['text'], tr(start, length), clip_settings=clip,
                        style=draft.TextStyle(size=px / 6, color=_rgb(source.get('color', '#FFFFFF')), align=1), border=border)
                    font_by_id[seg.material_id] = source['font_path']
                    track_type = draft.TrackType.text
                else:
                    if kind == 'solid':
                        path = folder / f'assets/graphics/solid-{index:03d}.png'
                        Image.new('RGBA', (w, h), tuple(round(c * 255) for c in _rgb(source.get('color', '#FFFFFF'))) + (255,)).save(path)
                    else:
                        path = Path(source['path'])
                    if 'freeze_at' in layer:
                        held = folder / f'assets/graphics/freeze-{index:03d}.png'
                        run([cfg['ffmpeg'], '-v', 'error', '-ss', str(layer['freeze_at']), '-i', path,
                             '-frames:v', '1', '-an', '-n', held])
                        if not held.is_file(): raise EditError('FREEZE_EMPTY', '定格位置未产生可用帧。')
                        path = held
                    material = draft.VideoMaterial(str(path))
                    metadata = probe(path, cfg)
                    material.width = metadata['width']; material.height = metadata['height']
                    src = None if material.material_type == 'photo' else tr(layer.get('source_in', 0), length * layer.get('speed', 1))
                    seg = draft.VideoSegment(material, tr(start, length), source_timerange=src, volume=0, clip_settings=clip)
                    track_type = draft.TrackType.video
                    if layer.get('mask'):
                        _native_mask(seg, layer, canvas, cfg, resource_paths)
                    if layer.get('blend', 'normal') != 'normal':
                        seg.set_mix_mode(getattr(draft.MixModeType, MIX_NAMES[layer['blend']]))
                        resource_paths[seg.mix_modes[-1].global_id] = _mix_resource(layer['blend'], cfg)
                mapping = {'x': draft.KeyframeProperty.position_x, 'y': draft.KeyframeProperty.position_y,
                           'scale': draft.KeyframeProperty.uniform_scale, 'rotation': draft.KeyframeProperty.rotation,
                           'opacity': draft.KeyframeProperty.alpha}
                samples = transform_samples(layer, fps, length)
                varying = [prop for prop in mapping if any(abs(row[prop] - samples[0][prop]) > 1e-10 for row in samples[1:])]
                for prop in varying:
                    for row in samples:
                        seg.add_keyframe(mapping[prop], _us(row['time']), row[prop])
                track = project.append_tracks([draft.TrackSpec(track_type, f'{index + 1:02d} · {layer["id"]}')])[0]
                project.add_segment(seg, track=track)
                track_reports.append({'id': layer['id'], 'segment_id': seg.segment_id, 'material_id': seg.material_id,
                    'native_transform_properties': varying, 'keyframes_per_property': len(samples) if varying else 0,
                    'baked_composition': whole_baked,
                    'baked_layer_operations': partial.get(layer['id'], []),
                    'native_layer_transforms_editable': True,
                    'native_source_text_editable': kind == 'text',
                    'native_mask': bool(layer.get('mask')),
                    'native_mix': layer.get('blend', 'normal') != 'normal'})
            project.save()
            for path in (temp_root / name).iterdir():
                if path.is_file(): shutil.copy2(path, folder / path.name)
        content = read(folder / 'draft_content.json'); meta = read(folder / 'draft_meta_info.json')
        masks = content['materials'].pop('masks', [])
        content['materials'].setdefault('common_mask', []).extend(masks)
        bound_resources = {}
        for values in content['materials'].values():
            if not isinstance(values, list): continue
            for item in values:
                if item.get('id') in resource_paths:
                    source_dir = resource_paths[item['id']]
                    if source_dir is None: raise EditError('NATIVE_RESOURCE_MISSING', '原生资源在导出期间消失。')
                    key = str(source_dir)
                    if key not in bound_resources:
                        dest = folder / 'assets/native-resources' / source_dir.parent.name / source_dir.name
                        shutil.copytree(source_dir, dest)
                        bound_resources[key] = dest
                        resources.append({'kind': 'native_effect_resource', 'source': key,
                                          'path': str(dest), 'config_sha256': sha256(dest / 'config.json')})
                    item['path'] = str(bound_resources[key]).replace('\\', '/')
        for material in content['materials'].get('texts', []):
            font = font_by_id[material['id']].replace('\\', '/')
            rich = json.loads(material['content'])
            for style in rich['styles']: style['font'] = {'id': '', 'path': font}
            material['content'] = json.dumps(rich, ensure_ascii=False)
            material.update(font_path=font, font_name=Path(font).stem, font_title=Path(font).stem)
        meta.update(draft_fold_path=str(folder), draft_root_path=str(folder.parent), draft_name=name)
        encode(folder, content, meta, cfg)
        # Every media/font/effect reference inside the package can be rebased.
        paths = {}
        def collect(obj):
            if isinstance(obj, dict):
                for value in obj.values(): collect(value)
            elif isinstance(obj, list):
                for value in obj: collect(value)
            elif isinstance(obj, str):
                try:
                    p = Path(obj)
                    if p.is_absolute() and p.exists() and p.resolve().is_relative_to(folder):
                        paths[obj] = p.resolve().relative_to(folder).as_posix()
                except (OSError, ValueError): pass
        collect(content)
        for font in font_by_id.values(): paths[font] = Path(font).relative_to(folder).as_posix()
        write(folder / 'portable-manifest.json', {'schema_version': '1.0', 'original_root': str(folder),
              'media_paths': paths, 'font_path': cfg.get('font_path'), 'note': 'Native technique package; rebase the current draft, never reconstruct edited parameters.'})
        shutil.copy2(ROOT / 'scripts/open-package.ps1', folder / 'open-package.ps1')
        (folder / '修复并打开工程.cmd').write_text(
            '@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-package.ps1"\r\n', encoding='ascii')
        (folder / '打开技巧工程.txt').write_text(
            '保存并正常退出剪映后，运行“修复并打开工程.cmd”，选择已安装的video-edit。\n'
            '保留整个文件夹；修复读取当前草稿并重定位，不重建已编辑参数。\n'
            '可编辑与已烘焙操作见technique-native-report.json；结构检查不代表界面验收。\n', encoding='utf-8')
        report.update(draft_path=str(folder), draft_id=content['id'], duration_seconds=content['duration'] / 1e6,
            encrypted_roundtrip=True, registered=False, ui_verified=False, source_hashes_verified=True,
            original_audio_muted=True, tracks=track_reports, resources=resources,
            route='derived_composition' if whole_baked else 'hybrid_layers' if partial else 'native_layers',
            native_effect_parameters_editable=report['native'],
            native_layer_transforms_editable=not whole_baked,
            equivalence='Structural parameter mapping; editor rendering/layout/polarity/export not yet verified.',
            gaps=['No editor open/edit/save/export verification is implied by encrypted round-trip.',
                  'Native text metrics, blend/color management and linear-mask polarity require editor comparison.',
                  'Derived operations are baked; their inner parameters remain in the typed sidecar, not native effect controls.'])
        write(folder / 'technique-native-report.json', report)
        return report
    except Exception as exc:
        write(folder / 'failure.json', {'message': str(exc), 'code': getattr(exc, 'code', 'NATIVE_TECHNIQUE_FAILED')})
        raise

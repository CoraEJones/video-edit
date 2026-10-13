"""Original SDR creative looks, deterministic LUTs, and shared render filters.

Color settings are mathematical parameters, not Jianying slider values. A look
expects BT.709 SDR encoded RGB. Corrections precede the look; strength affects
only the look. This module never changes or substitutes a source media file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile

from .common import EditError, ROOT, read, sha256, write

RECIPE_PATH = ROOT / 'assets/color/recipes.json'
GENERATOR_VERSION = '1.0'
LUT_SIZE = 33
HDR_TRANSFERS = ('arib-std-b67', 'smpte2084')
DEFAULTS = {'enabled': True, 'look': 'none', 'strength': 1.0, 'exposure_ev': 0.0,
            'contrast': 1.0, 'gamma': 1.0, 'saturation': 1.0,
            'white_balance': [1.0, 1.0, 1.0], 'input_space': None}
RANGES = {'strength': (0, 1), 'exposure_ev': (-3, 3), 'contrast': (.5, 1.5),
          'gamma': (.5, 2), 'saturation': (0, 2)}


def catalog():
    """Return the exact original recipes, with stable 1..20 numbers and slugs."""
    return read(RECIPE_PATH)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize(settings):
    if not isinstance(settings, dict):
        raise ValueError('color 必须为对象；用 enabled:false 关闭')
    unknown = set(settings) - set(DEFAULTS)
    if unknown:
        raise ValueError('未知 color 字段：' + ', '.join(sorted(unknown)))
    result = dict(DEFAULTS, **settings)
    if not isinstance(result['enabled'], bool):
        raise ValueError('enabled 必须为布尔值')
    for key, (low, high) in RANGES.items():
        if not number(result[key]) or not low <= result[key] <= high:
            raise ValueError(f'{key} 需要 {low} 到 {high} 的有限数值')
    gains = result['white_balance']
    if not isinstance(gains, list) or len(gains) != 3 or not all(number(v) and .8 <= v <= 1.25 for v in gains):
        raise ValueError('white_balance 需要三个 0.8 到 1.25 的 RGB 线性增益')
    if result['input_space'] not in (None, 'bt709_sdr'):
        raise ValueError('input_space 仅支持 bt709_sdr；Log 输入需先进行正确的技术转换')
    look = result['look']
    recipes = catalog()
    if isinstance(look, int) and not isinstance(look, bool):
        match = next((p for p in recipes if p['number'] == look), None)
    elif isinstance(look, str):
        match = next((p for p in recipes if look in (p['slug'], p['stem'])), None)
    else:
        match = None
    if look != 'none' and match is None:
        raise ValueError('look 需要 1..20 编号、目录中的 slug，或 none')
    result['look'] = match['slug'] if match else 'none'
    result['white_balance'] = list(gains)
    return result


def effective_color(plan, item=None, shot=None):
    merged = {}
    for owner in (plan, shot, item):
        if owner is not None and 'color' in owner:
            if not isinstance(owner['color'], dict):
                raise ValueError('color 必须为对象')
            merged.update(owner['color'])
    return normalize(merged)


def is_active(settings):
    return settings['enabled'] and (
        (settings['look'] != 'none' and settings['strength'] != 0)
        or settings['exposure_ev'] != 0 or settings['contrast'] != 1
        or settings['gamma'] != 1 or settings['saturation'] != 1
        or settings['white_balance'] != [1, 1, 1])


def color_items(plan):
    """Yield actual source clips; a split-screen dummy black is not a clip."""
    shots = {s.get('index'): s for s in plan.get('shots', [])}
    for group in ('shots', 'panels', 'visual_layers'):
        for i, item in enumerate(plan.get(group, [])):
            if group == 'shots' and str(item.get('purpose', '')).startswith('panels_'):
                continue
            parent = shots.get(item.get('index')) if group == 'panels' else None
            yield f'{group}[{i}]', item, parent


def input_transform(asset, settings):
    metadata = asset.get('source_metadata', asset)
    transfer = metadata.get('color_transfer')
    primaries = metadata.get('color_primaries')
    matrix = metadata.get('color_space')
    if transfer in HDR_TRANSFERS:
        if primaries not in ('bt2020', 'bt709') or matrix not in ('bt2020nc', 'bt709'):
            raise ValueError('HDR 调色需要已知 primaries 和 matrix 元数据，不能猜测输入色彩空间')
        return hdr_filter(asset)
    if transfer in ('log100', 'log316') or str(transfer).lower().startswith(('slog', 'clog', 'vlog', 'log')):
        raise ValueError('Log 尚不支持直接套创意 LUT；请先完成相机对应的 Log→BT.709 SDR 技术转换')
    if transfer not in (None, '', 'unknown', 'unspecified', 'bt709'):
        raise ValueError(f'输入传递函数 {transfer} 尚不支持；请先转换到 BT.709 SDR')
    if primaries not in (None, '', 'unknown', 'unspecified', 'bt709') or matrix not in (None, '', 'unknown', 'unspecified', 'bt709', 'gbr'):
        raise ValueError('输入 primaries/matrix 不是 BT.709，需先做技术转换')
    if transfer != 'bt709' and settings['input_space'] != 'bt709_sdr':
        raise ValueError('输入色彩标签未知；确认已为 BT.709 SDR 后显式设置 color.input_space=bt709_sdr')
    return ''


def hdr_filter(asset):
    """Existing renderer HDR→SDR transform, shared by preview and MP4."""
    if asset.get('source_metadata', asset).get('color_transfer') in HDR_TRANSFERS:
        return 'zscale=t=linear:npl=100,format=gbrpf32le,tonemap=tonemap=mobius:desat=0,zscale=p=bt709:t=bt709:m=bt709:r=tv,'
    return ''


def validate_color(plan, rows, issue):
    """Validate declarations and inheritance. The caller owns error collection."""
    lookup = {r['id']: r for r in rows}
    declarations = [('color', plan.get('color'))] if 'color' in plan else []
    for group in ('shots', 'panels', 'visual_layers'):
        declarations += [(f'{group}[{i}].color', item['color'])
                         for i, item in enumerate(plan.get(group, [])) if 'color' in item]
    invalid = False
    for where, declaration in declarations:
        try:
            normalize(declaration)
        except (ValueError, TypeError) as exc:
            issue('COLOR_SETTINGS', where, str(exc)); invalid = True
    if invalid:
        return
    for where, item, parent in color_items(plan):
        settings = effective_color(plan, item, parent)
        if is_active(settings) and item.get('id') in lookup:
            try:
                input_transform(lookup[item['id']], settings)
            except ValueError as exc:
                issue('COLOR_INPUT_SPACE', where + '.color', str(exc))


def assert_native_color_supported(plan):
    if any(is_active(effective_color(plan, item, parent)) for _, item, parent in color_items(plan)):
        raise EditError('COLOR_NATIVE_UNSUPPORTED',
                        '尚未验证剪映原生 LUT/校色参数支持。带调色计划请导出 MP4，或生成 LUT 后在剪映手工应用并复核；不能静默丢弃调色。')


def rgb_to_hsv(rgb):
    import numpy as np
    maximum=rgb.max(axis=-1); minimum=rgb.min(axis=-1); delta=maximum-minimum
    safe=np.where(delta>1e-8, delta, 1)
    h=np.zeros_like(maximum)
    for ch, formula in [(0,(rgb[...,1]-rgb[...,2])/safe), (1,(rgb[...,2]-rgb[...,0])/safe+2), (2,(rgb[...,0]-rgb[...,1])/safe+4)]:
        h=np.where((maximum==rgb[...,ch]) & (delta>1e-8), formula, h)
    h=(h/6)%1
    s=np.where(maximum>1e-8, delta/np.maximum(maximum,1e-8), 0)
    return np.stack([h,s,maximum],axis=-1)


def hsv_to_rgb(hsv):
    import numpy as np
    h,s,v=np.moveaxis(hsv,-1,0)
    i=np.floor(h*6).astype(int); f=h*6-i
    p=v*(1-s); q=v*(1-f*s); t=v*(1-(1-f)*s)
    choices=np.stack([np.stack(x,axis=-1) for x in [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)]],axis=0)
    return np.take_along_axis(choices, (i%6)[None,...,None],axis=0)[0]


def interpolate(rgb, points):
    import numpy as np
    pts=np.array(points)
    return np.interp(rgb,pts[:,0],pts[:,1])


def apply_look(rgb, p):
    """Numerically identical to the user's original LUT lab grade.py."""
    import numpy as np
    luma=np.array([0.2126, 0.7152, 0.0722])
    x=np.clip(rgb,0,1).astype(float)
    x=np.clip((x**(1/p['gamma'])-.5)*p['contrast']+.5+p['brightness'],0,1)
    x=interpolate(x,p['curve'])
    for name,points in p['channel_curves'].items():
        ch='rgb'.index(name); x[...,ch]=interpolate(x[...,ch],points)
    tonal=x.copy();y=x@luma
    x=y[...,None]+(x-y[...,None])*p['saturation']
    if p['matrix'] is not None: x=x@np.array(p['matrix']).T
    protection_low=np.minimum(1,y/.08);protection_high=np.minimum(1,(1-y)/.08)
    x += ((1-y)**2*protection_low)[...,None]*np.array(p['shadows'])
    x += (4*y*(1-y))[...,None]*np.array(p['midtones'])
    x += (y**2*protection_high)[...,None]*np.array(p['highlights'])
    x=np.clip(x,0,1)
    if p['hue_bands']:
        hsv=rgb_to_hsv(x); original_h=hsv[...,0]*360
        shift=np.zeros_like(y); sat_factor=np.ones_like(y)
        for band in p['hue_bands']:
            distance=np.abs((original_h-band['center']+180)%360-180)
            weight=np.exp(-.5*(distance/band['width'])**2)*np.minimum(hsv[...,1]/.20,1)
            shift+=weight*band['hue']; sat_factor+=weight*(band['sat']-1)
        hsv[...,0]=(hsv[...,0]+shift/360)%1;hsv[...,1]=np.clip(hsv[...,1]*sat_factor,0,1)
        x=hsv_to_rgb(hsv)
    if p['skin_protect']:
        hsv=rgb_to_hsv(tonal);distance=np.abs((hsv[...,0]*360-30+180)%360-180)
        mask=np.exp(-.5*(distance/22)**2)*np.minimum(hsv[...,1]/.20,1)*p['skin_protect']
        # Warm-hue mask also protects sand/wood: this is not face detection.
        x=x*(1-mask[...,None])+tonal*mask[...,None]
    return np.clip(x,0,1)


def transform_rgb(rgb, settings):
    """Reference math used to generate CUBE samples; all computation float64."""
    import numpy as np
    settings = normalize(settings)
    x = np.clip(np.asarray(rgb, dtype=float), 0, 1)
    if not is_active(settings):
        return x.copy()
    if settings['exposure_ev'] != 0 or settings['white_balance'] != [1, 1, 1]:
        linear = np.where(x < .081, x / 4.5, ((x + .099) / 1.099) ** (1 / .45))
        linear = np.clip(linear * 2 ** settings['exposure_ev'] * np.array(settings['white_balance']), 0, 1)
        x = np.where(linear < .018, 4.5 * linear, 1.099 * linear ** .45 - .099)
    if settings['gamma'] != 1:
        x = x ** (1 / settings['gamma'])
    if settings['contrast'] != 1:
        x = (x - .5) * settings['contrast'] + .5
    x = np.clip(x, 0, 1)
    if settings['saturation'] != 1:
        y = x @ np.array([.2126, .7152, .0722])
        x = np.clip(y[..., None] + (x - y[..., None]) * settings['saturation'], 0, 1)
    if settings['look'] != 'none' and settings['strength'] != 0:
        p = next(p for p in catalog() if p['slug'] == settings['look'])
        x = x * (1 - settings['strength']) + apply_look(x, p) * settings['strength']
    return np.clip(x, 0, 1)


def generate_lut(settings, directory, size=LUT_SIZE):
    """Generate/cache a full correction→look CUBE; validate cached SHA-256."""
    import numpy as np
    settings = normalize(settings)
    if not isinstance(size, int) or isinstance(size, bool) or not 2 <= size <= 65:
        raise ValueError('LUT size must be 2..65')
    signature = {'generator_version': GENERATOR_VERSION, 'generator_sha256': sha256(__file__),
                 'recipes_sha256': sha256(RECIPE_PATH), 'size': size, 'settings': settings}
    key = hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    directory = Path(directory);directory.mkdir(parents=True, exist_ok=True)
    path = directory / (key + '.cube');manifest_path = directory / (key + '.json')
    if path.is_file() and manifest_path.is_file():
        try:
            manifest = read(manifest_path)
            if manifest.get('signature') == signature and sha256(path) == manifest.get('sha256'):
                return path, manifest
        except (OSError, EditError, TypeError):
            pass
    b,g,r = np.meshgrid(*(np.linspace(0, 1, size),) * 3, indexing='ij')
    grid = np.stack([r,g,b], axis=-1).reshape(-1,3)
    output = transform_rgb(grid, settings)
    if not np.isfinite(output).all() or output.min() < 0 or output.max() > 1:
        raise ValueError('Invalid LUT output')
    with tempfile.NamedTemporaryFile('w', encoding='ascii', newline='\n', dir=directory, delete=False, suffix='.tmp') as handle:
        temporary = Path(handle.name)
        handle.write(f'TITLE "video-edit {settings["look"]} {key[:12]}"\n# Original BT709 SDR creative grade. Corrections precede look.\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        np.savetxt(handle, output, fmt='%.7f')
    temporary.replace(path)
    manifest = {'signature': signature, 'sha256': sha256(path), 'sample_count': size ** 3,
                'domain': 'BT.709 SDR encoded RGB 0..1', 'interpolation': 'tetrahedral'}
    write(manifest_path, manifest)
    return path, manifest


def input_color_filter(plan, item, asset, folder, shot=None):
    """Prefix for both renderers. Paths contain only ASCII relative components."""
    settings = effective_color(plan, item, shot)
    if not is_active(settings):
        return hdr_filter(asset)
    prefix = input_transform(asset, settings)
    path, manifest = generate_lut(settings, Path(folder) / 'assets/color')
    relative = path.relative_to(Path(folder)).as_posix()
    # This deliberately avoids absolute C:\... and source filenames in filters.
    # A generated SHA basename needs no shell/filter escaping or drive colon.
    result = prefix + f"format=gbrapf32le,lut3d=file='{relative}':interp=tetrahedral,"
    report_path = Path(folder) / 'color-report.json'
    report = read(report_path) if report_path.is_file() else {'generator_version': GENERATOR_VERSION, 'clips': []}
    record = {'id': item.get('id'), 'index': item.get('index'), 'start': item.get('start'),
              'source_in': item.get('source_in', 0), 'duration': item.get('duration'),
              'panel': item.get('panel'), 'settings': settings, 'lut': relative,
              'lut_sha256': manifest['sha256'], 'generator_sha256': manifest['signature']['generator_sha256'],
              'recipes_sha256': manifest['signature']['recipes_sha256'],
              'input_metadata': asset.get('source_metadata', {}), 'hdr_tonemapped': bool(prefix),
              'order': ['HDR to SDR if detected', 'linear exposure and RGB gains', 'gamma', 'contrast', 'saturation', 'creative look strength']}
    # Repeated preview/final calls update the same per-clip record.
    key_fields = ('id', 'index', 'start', 'panel', 'source_in', 'duration', 'lut')
    report['clips'] = [r for r in report['clips'] if tuple(r.get(k) for k in key_fields) !=
                       tuple(record.get(k) for k in key_fields)]
    report['clips'].append(record);write(report_path, report)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('catalog')
    export = sub.add_parser('export-luts')
    export.add_argument('--out', required=True)
    export.add_argument('--strength', type=float, default=1.0)
    args = parser.parse_args()
    if args.command == 'catalog':
        print(json.dumps(catalog(), ensure_ascii=False, indent=2));return
    results = []
    for recipe in catalog():
        path, manifest = generate_lut({'look': recipe['slug'], 'strength': args.strength}, args.out)
        named = Path(args.out) / (recipe['stem'] + '.cube')
        # No source videos are read or changed. These copies have friendly names
        # for manual import into an editor; the hash cache remains reproducible.
        named.write_bytes(path.read_bytes())
        results.append({'look': recipe['slug'], 'path': str(named), 'sha256': manifest['sha256']})
    write(Path(args.out) / 'catalog.json', results)
    print(json.dumps({'count': len(results), 'output': args.out}, ensure_ascii=False))


if __name__ == '__main__':
    main()

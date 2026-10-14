"""Independent calligraphic title intros, with one shared motion table.

This independent dual-delivery tool does not touch Jianying's draft registry.
PNG artwork is an editable image layer, not editable character text.
Encrypted codec round-trip is explicitly not an editor visual verification.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
from fractions import Fraction
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from PIL import Image, ImageDraw

DEFAULT_SKILL = Path(__file__).resolve().parents[1]
PIPELINE_VERSION = 'title-intro-pipeline.1.1.0'
sys.path.insert(0, str(DEFAULT_SKILL / 'scripts'))
from video_edit.common import read, write, sha256, probe, run, ROOT, load_config
from video_edit.image_color import convert_image
from video_edit.native import codec, encode


def finite(value, label, lower=None, upper=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    if lower is not None and value < lower or upper is not None and value > upper:
        raise ValueError(f'{label} outside [{lower}, {upper}]: {value}')
    return float(value)


def actual_path(value, base):
    p = Path(value).expanduser()
    p = (base / p if not p.is_absolute() else p).resolve()
    if not p.is_file():
        raise ValueError(f'File missing: {p}')
    return p


def inspect_png(path):
    with Image.open(path) as im:
        if im.format != 'PNG' or 'A' not in im.getbands():
            raise ValueError(f'Artwork requires an actual alpha PNG: {path}')
        alpha = im.getchannel('A')
        low, high = alpha.getextrema()
        visible = alpha.point(lambda x: 255 if x > 16 else 0).getbbox()
        if low == 255 or high == 0 or visible is None:
            raise ValueError(f'Artwork must have visible and transparent pixels: {path}')
        return {'width': im.width, 'height': im.height, 'alpha_extrema': [low, high],
                'alpha_bbox': list(alpha.getbbox()), 'visible_alpha_bbox_gt16': list(visible)}


def valid_id(value):
    return isinstance(value,str) and bool(value.strip()) and len(value)<=80 and not any(c in value for c in '/\\:*?"<>|') and not any(ord(c)<32 for c in value)


def source_geometry(metadata,canvas):
    """Contain the measured display aspect ratio, with explicit raster rounding.

    Native source material is described in its measured display-rotation pixel
    dimensions; native transforms apply the same final raster fit. Whether the
    editor additionally interprets the original SAR requires visual UI QA.
    """
    raw=metadata.get('sample_aspect_ratio')
    ratio=1 if raw in (None,'','N/A','0:1') else float(Fraction(raw.replace(':','/')))
    finite(ratio,'sample aspect ratio',.1,10)
    sw,sh=metadata['width'],metadata['height'];w,h=canvas['width'],canvas['height']
    rotated=round(abs(metadata.get('rotation',0)))%180==90
    dw,dh=(sw,sh*ratio) if rotated else (sw*ratio,sh)
    fit=min(w/dw,h/dh);tw=min(w,max(1,round(dw*fit)));th=min(h,max(1,round(dh*fit)))
    x,y=(w-tw)//2,(h-th)//2;base=min(w/sw,h/sh)
    return {'sample_aspect_ratio':raw,'interpreted_sar':ratio,'display_width':dw,'display_height':dh,
        'raster_width':tw,'raster_height':th,'raster_x':x,'raster_y':y,
        'native_scale_x':tw/(sw*base),'native_scale_y':th/(sh*base),
        'native_transform_x':2*(x+tw/2-w/2)/w,'native_transform_y':-2*(y+th/2-h/2)/h,
        'rounding':'Nearest integer display size within canvas; integer pad position. No source pixels or metadata are rewritten.',
        'native_sar_rendering_ui_verified':False}


def validate_design(document, base, cfg):
    d = deepcopy(document)
    if d.get('schema_version') != 'title-intro.1.0':
        raise ValueError('schema_version must be title-intro.1.0')
    if not valid_id(d.get('id')):
        raise ValueError('A non-empty, filesystem-safe id is required')
    if not isinstance(d.get('title_text'), str) or not d['title_text'].strip():
        raise ValueError('title_text is required for explicit human character review')
    c = d.setdefault('canvas', {})
    for key, default, low, high in [('width', 854, 64, 1920), ('height', 480, 64, 1920), ('fps', 60, 24, 60)]:
        value = c.setdefault(key, default)
        finite(value, key, low, high)
        if value != int(value) or key != 'fps' and int(value) % 2:
            raise ValueError('Canvas width/height must be even integers; fps an integer')
        c[key] = int(value)
    s = d['source']; s['path'] = str(actual_path(s['path'], base))
    s['source_in_s'] = finite(s.get('source_in_s', 0), 'source_in_s', 0)
    s['duration_s'] = finite(s['duration_s'], 'duration_s', 4, 6)
    n = round(s['duration_s'] * c['fps'])
    if abs(n / c['fps'] - s['duration_s']) > 1e-8:
        raise ValueError('duration_s must align to a project frame')
    metadata = probe(s['path'], cfg)
    if not metadata.get('duration') or s['source_in_s'] + s['duration_s'] > metadata['duration'] + .001:
        raise ValueError('Source interval exceeds measured source duration')
    if metadata.get('color_transfer') in ('smpte2084', 'arib-std-b67'):
        raise ValueError('Known HDR source needs a separately confirmed tone-mapping workflow')
    digest = sha256(s['path'])
    if s.get('sha256') and s['sha256'] != digest:
        raise ValueError('Source SHA256 does not match the design card')
    s['sha256'] = digest; s['metadata'] = metadata
    s['display_geometry']=source_geometry(metadata,c)
    w, h, fps, duration = c['width'], c['height'], c['fps'], s['duration_s']
    layers = [dict(d['title'], id='title')] + d.get('accessories', [])
    ids = set()
    for index, layer in enumerate(layers):
        ident = layer.setdefault('id', f'accessory-{index:02d}')
        if not valid_id(ident) or ident in ids:
            raise ValueError('Layer ids must be unique, filesystem-safe strings')
        ids.add(ident)
        layer['path'] = str(actual_path(layer['path'], base))
        layer['sha256'] = sha256(layer['path']); layer['png'] = inspect_png(layer['path'])
        for key, low, high in [('x_px', -4*w, 4*w), ('y_px', -4*h, 4*h), ('width_px', 1, 8*w)]:
            layer[key] = finite(layer[key], f'{ident}.{key}', low, high)
        layer['start_s'] = finite(layer.get('start_s', 0), 'start_s', 0, duration)
        layer['end_s'] = finite(layer.get('end_s', duration), 'end_s', layer['start_s'] + 1/fps, duration)
        if any(abs(round(layer[k]*fps)/fps-layer[k])>1e-8 for k in ('start_s','end_s')):
            raise ValueError(f'{ident}: start/end must align to project frames')
        motion = layer.setdefault('motion', {})
        if motion.setdefault('type', 'slide_fade') not in ('slide_fade', 'scale_fade', 'staggered', 'curved_path', 'rotate_settle'):
            raise ValueError('Unknown motion type')
        if motion.setdefault('easing', 'smoothstep') not in ('smoothstep', 'linear'):
            raise ValueError('easing must be smoothstep or linear')
        for key, default, low, high in [('enter_s', .65, 1/fps, duration), ('exit_s', .45, 1/fps, duration),
                ('dx_px', 20, -w, w), ('dy_px', 0, -h, h), ('from_scale', .96, .5, 1.5),
                ('stagger_s', 0, 0, duration), ('exit_dx_px', 0, -w, w), ('exit_dy_px', -4, -h, h),
                ('from_rotation_deg', -6 if motion['type']=='rotate_settle' else 0, -360, 360),
                ('rotation_deg', 0, -360, 360), ('settle_s', 0, 0, 1.5),
                ('overshoot_px', 0, 0, 24), ('overshoot_rotation_deg', 0, -20, 20)]:
            motion[key] = finite(motion.get(key, default), f'{ident}.{key}', low, high)
        span = layer['end_s'] - layer['start_s']
        if motion['stagger_s'] + motion['enter_s'] + motion['settle_s'] + motion['exit_s'] > span + 1e-8:
            raise ValueError(f'{ident}: enter/stagger/exit leave no valid hold')
        if (motion['overshoot_px'] or motion['overshoot_rotation_deg']) and not motion['settle_s']:
            raise ValueError('Overshoot requires a positive settle_s')
        if motion['type']=='curved_path':
            points=motion.get('cubic_bezier_points_px')
            if not isinstance(points,list) or len(points)!=4 or any(not isinstance(p,list) or len(p)!=2 for p in points):
                raise ValueError('curved_path requires exactly four [dx,dy] cubic_bezier_points_px')
            for p in points:
                finite(p[0],'bezier dx',-2*w,2*w);finite(p[1],'bezier dy',-2*h,2*h)
            if points[-1]!=[0,0]:raise ValueError('Cubic path must end at [0,0], the designed resting position')
        keys=motion.get('rotation_keyframes')
        if keys is not None:
            if not isinstance(keys,list) or not 2<=len(keys)<=200:raise ValueError('rotation_keyframes requires 2–200 keys')
            previous=-1
            for key in keys:
                t=finite(key['time_s'],'rotation key time_s',0,span)
                finite(key['rotation_deg'],'rotation key angle',-360,360)
                if t<=previous or abs(round(t*fps)/fps-t)>1e-8:raise ValueError('Rotation key times must increase on project frames')
                previous=t
            if keys[0]['time_s']!=0:raise ValueError('rotation_keyframes must start at local time 0')
        margin = finite(layer.get('safe_margin_px', 16 if index == 0 else 0), 'safe_margin_px', 0, min(w,h)/2)
        ratio = layer['width_px'] / layer['png']['width']
        a,b,x,y = layer['png']['visible_alpha_bbox_gt16']
        bbox = [layer['x_px'] + a*ratio, layer['y_px'] + b*ratio,
                layer['x_px'] + x*ratio, layer['y_px'] + y*ratio]
        layer['visible_bbox_at_rest_px'] = bbox
        pivot=layer.get('pivot_px',[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2])
        if not isinstance(pivot,list) or len(pivot)!=2:raise ValueError('pivot_px must be [canvas_x,canvas_y]')
        finite(pivot[0],'pivot x',-w,2*w);finite(pivot[1],'pivot y',-h,2*h)
        layer['pivot_px']=pivot
        layer['canvas_size_px']=[w,h]
        layer['safe_margin_px'] = margin
        rest_angle=motion['rotation_keyframes'][-1]['rotation_deg'] if motion.get('rotation_keyframes') else motion['rotation_deg']
        theta=math.radians(rest_angle);co,si=math.cos(theta),math.sin(theta);px,py=pivot
        corners=[(px+co*(x-px)-si*(y-py),py+si*(x-px)+co*(y-py)) for x in (bbox[0],bbox[2]) for y in (bbox[1],bbox[3])]
        rotated=[min(x for x,y in corners),min(y for x,y in corners),max(x for x,y in corners),max(y for x,y in corners)]
        layer['visible_bbox_rotated_rest_px']=rotated
        if rotated[0] < margin-.5 or rotated[1] < margin-.5 or rotated[2] > w-margin+.5 or rotated[3] > h-margin+.5:
            raise ValueError(f'{ident}: actual alpha glyphs exceed safe resting bounds: {rotated}')
        layer['layer_duration_s'] = span
    d['layers'] = layers
    return d


def motion_table(layer, fps):
    """Absolute project-frame samples; same rows consumed by both backends."""
    m = layer['motion']; rows = []
    count = round(layer['layer_duration_s'] * fps)
    def ease(q):
        q = max(0, min(1, q))
        return q*q*(3-2*q) if m['easing'] == 'smoothstep' else q
    for frame in range(count):
        t = frame / fps
        enter = ease((t-m['stagger_s'])/m['enter_s'])
        exit = ease((t-(layer['layer_duration_s']-m['exit_s']))/m['exit_s'])
        opacity = enter * (1-exit)
        points=m.get('cubic_bezier_points_px') if m['type']=='curved_path' else [[m['dx_px'],m['dy_px']]]
        if len(points)==4:
            dx=sum((1-enter)**(3-i)*enter**i*k*points[i][0] for i,k in enumerate((1,3,3,1)))
            dy=sum((1-enter)**(3-i)*enter**i*k*points[i][1] for i,k in enumerate((1,3,3,1)))
        else:dx,dy=(1-enter)*m['dx_px'],(1-enter)*m['dy_px']
        over=enter if t<=m['stagger_s']+m['enter_s'] else (1-ease((t-m['stagger_s']-m['enter_s'])/m['settle_s']) if m['settle_s'] else 0)
        length=math.hypot(*points[0]);direction=(-points[0][0]/length,-points[0][1]/length) if length else (1,0)
        dx+=direction[0]*m['overshoot_px']*over+exit*m['exit_dx_px']
        dy+=direction[1]*m['overshoot_px']*over+exit*m['exit_dy_px']
        scale = m['from_scale'] + (1-m['from_scale'])*enter if m['type'] == 'scale_fade' else 1.0
        angle=m['from_rotation_deg']+(m['rotation_deg']-m['from_rotation_deg'])*enter+m['overshoot_rotation_deg']*over
        keys=m.get('rotation_keyframes')
        if keys:
            angle=keys[-1]['rotation_deg']
            for a,b in zip(keys,keys[1:]):
                if t<=b['time_s']:
                    q=ease((t-a['time_s'])/(b['time_s']-a['time_s']))
                    angle=a['rotation_deg']+(b['rotation_deg']-a['rotation_deg'])*q
                    break
        # Native PNG rotation uses the canvas center. This compensation keeps
        # the designed glyph pivot fixed, so title rotation looks intentional.
        px,py=layer['pivot_px'];cw,ch=layer['canvas_size_px'];vx,vy=px-cw/2,py-ch/2
        theta=math.radians(angle);co,si=math.cos(theta),math.sin(theta)
        native_dx=dx+vx-scale*(co*vx-si*vy)
        native_dy=dy+vy-scale*(si*vx+co*vy)
        rows.append({'frame': frame, 'time_s': t, 'project_time_s': layer['start_s']+t,
                     'path_dx_px':dx,'path_dy_px':dy,'dx_px':native_dx,'dy_px':native_dy,
                     'scale': scale, 'rotation_deg':angle,'opacity': opacity})
    return rows


def copy_exact(source, dest):
    source = Path(source); dest = Path(dest)
    digest = sha256(source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if sha256(dest) != digest:
            raise ValueError(f'Existing resource changed; refusing overwrite: {dest}')
    else:
        shutil.copy2(source, dest)
    if sha256(source) != digest or sha256(dest) != digest:
        raise ValueError('Source changed while copying')
    return {'source': str(source), 'path': str(dest), 'sha256': digest}


def prepare(d, output):
    resource_dir = output / 'resources'; result = []
    copy_exact(d['source']['path'], resource_dir / 'source' / Path(d['source']['path']).name)
    for index, layer in enumerate(d['layers']):
        dest = resource_dir / f'{index:02d}-{layer["id"]}'
        original = dest / 'artwork-original.png'
        copy_exact(layer['path'], original)
        normalized = dest / 'artwork-bt709.png'
        if not normalized.exists():
            convert_image(original, normalized, 'srgb')
        color_report=read(normalized.with_suffix('.color.json'))
        if color_report['source_sha256']!=sha256(original) or color_report['output_sha256']!=sha256(normalized):
            raise ValueError('Prepared artwork color bridge fingerprint mismatch')
        with Image.open(original) as original_image, Image.open(normalized) as normalized_image:
            if original_image.convert('RGBA').getchannel('A').tobytes()!=normalized_image.convert('RGBA').getchannel('A').tobytes():
                raise ValueError('Color bridge unexpectedly changed artwork alpha')
        im = Image.open(normalized).convert('RGBA')
        target_w = round(layer['width_px']); target_h = round(im.height * target_w / im.width)
        resized = im.resize((target_w, target_h), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (d['canvas']['width'], d['canvas']['height']))
        # Placement only; the original generated file is preserved byte-for-byte.
        canvas.alpha_composite(resized, (round(layer['x_px']), round(layer['y_px'])))
        placed = dest / 'placed-layer-bt709.png'
        if not placed.exists():
            canvas.save(placed)
        else:
            with Image.open(placed) as existing:
                if existing.convert('RGBA').tobytes() != canvas.tobytes():
                    raise ValueError('Existing prepared layer differs')
        rows = motion_table(layer, d['canvas']['fps'])
        write(dest / 'motion-table.json', rows)
        result.append({'id': layer['id'], 'image': str(placed), 'rows': rows, 'design': layer})
    return result


def transformed_image(image, row, canvas):
    w,h = canvas['width'],canvas['height']; s = row['scale']; dx,dy=row['dx_px'],row['dy_px']
    theta=math.radians(row['rotation_deg']);co,si=math.cos(theta),math.sin(theta)
    inv = (co/s, si/s, w/2-(co*(w/2+dx)+si*(h/2+dy))/s,
           -si/s, co/s, h/2+(si*(w/2+dx)-co*(h/2+dy))/s)
    im = image.transform((w,h), Image.Transform.AFFINE, inv, Image.Resampling.BICUBIC)
    im.putalpha(im.getchannel('A').point(lambda x: round(x*row['opacity'])))
    return im


def render_mp4(d, prepared, output, cfg):
    target = output / 'title-intro.mp4'
    if target.exists():
        return verify_mp4(target, d, cfg)
    c=d['canvas']; w,h,fps=c['width'],c['height'],c['fps']; duration=d['source']['duration_s']
    geometry=d['source']['display_geometry'];tw,th=geometry['raster_width'],geometry['raster_height']
    graph=(f'[0:v]trim=duration={duration},setpts=PTS-STARTPTS,format=rgb24,'
           f'scale={tw}:{th}:flags=lanczos,setsar=1,'
           f'pad={w}:{h}:{geometry["raster_x"]}:{geometry["raster_y"]}:color=black,fps={fps}[bg];'
           '[bg][1:v]overlay=0:0:shortest=1:format=rgb,'
           'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[out]')
    args=[cfg['ffmpeg'],'-hide_banner','-loglevel','error','-ss',str(d['source']['source_in_s']),
        '-i',d['source']['path'],'-f','rawvideo','-pixel_format','rgba','-video_size',f'{w}x{h}',
        '-framerate',str(fps),'-i','pipe:0','-filter_complex',graph,'-map','[out]','-an',
        '-frames:v',str(round(duration*fps)),'-c:v','libx264','-preset','medium','-crf','18',
        '-threads',str(cfg.get('ffmpeg_threads',2)),'-color_primaries','bt709','-color_trc','bt709',
        '-colorspace','bt709','-color_range','tv','-movflags','+faststart','-n',str(target)]
    images=[Image.open(p['image']).convert('RGBA') for p in prepared]
    log=output/'ffmpeg-render.log'
    with log.open('wb') as err:
        p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            for frame in range(round(duration*fps)):
                t=frame/fps; combined=Image.new('RGBA',(w,h))
                for item,image in zip(prepared,images):
                    layer=item['design']; local=t-layer['start_s']; j=round(local*fps)
                    if local>=-1e-9 and 0<=j<len(item['rows']):
                        combined=Image.alpha_composite(combined, transformed_image(image,item['rows'][j],c))
                p.stdin.write(combined.tobytes())
            p.stdin.close()
            status=p.wait(timeout=180)
            if status:
                raise RuntimeError(f'FFmpeg failed with {status}: {log.read_text(errors="replace")[-2000:]}')
        except Exception:
            if p.poll() is None:
                p.kill(); p.wait()
            if target.exists():
                target.rename(output / f'title-intro.failed-{uuid.uuid4().hex[:8]}.mp4')
            raise
    return verify_mp4(target,d,cfg)


def verify_mp4(path,d,cfg):
    result=run([cfg['ffprobe'],'-v','error','-count_frames','-show_streams','-show_format','-of','json',path],timeout=90)
    obj=json.loads(result.stdout); streams=obj['streams']
    videos=[s for s in streams if s['codec_type']=='video']
    if len(videos)!=1 or any(s['codec_type']=='audio' for s in streams):
        raise ValueError('Output must contain exactly one video and no audio')
    v=videos[0]; expected=round(d['source']['duration_s']*d['canvas']['fps'])
    if int(v.get('nb_read_frames',0))!=expected or v['width']!=d['canvas']['width'] or v['height']!=d['canvas']['height']:
        raise ValueError('Output frame count / canvas mismatch')
    if v['codec_name']!='h264' or v['pix_fmt']!='yuv420p':
        raise ValueError('Output format mismatch')
    run([cfg['ffmpeg'],'-v','error','-i',path,'-map','0:v:0','-f','null','-'],timeout=180)
    return {'path':str(path),'sha256':sha256(path),'frame_count':expected,'full_decode_passed':True,
        'duration_seconds':float(obj['format']['duration']),'original_audio_muted':True,
        'audio_stream_count':0,'single_final_video_encode':True}


def build_native(d,prepared,output,cfg):
    import importlib.metadata
    if importlib.metadata.version('pyJianYingDraft') != '0.3.0':
        raise ValueError('This validated native backend requires the isolated pyJianYingDraft 0.3.0 runtime')
    import pyJianYingDraft as draft
    package=output/'jianying'
    if package.exists() and (package/'native-report.json').exists():
        report=read(package/'native-report.json')
        from pyJianYingDraft.draft_codec import load_json_object_with_codec
        content,encrypted=load_json_object_with_codec(package/'draft_content.json',content_codec=codec(cfg))
        if not encrypted or content['id']!=report['draft_id']:
            raise ValueError('Existing native package fails actual codec readback')
        for resource in report['resources']:
            if not Path(resource['path']).is_file() or sha256(resource['path'])!=resource['sha256']:
                raise ValueError('Existing native package resource changed; refusing automatic repair')
        return report
    if package.exists():
        package.rename(output/f'jianying.failed-{uuid.uuid4().hex[:8]}')
    package.mkdir()
    c=d['canvas']; w,h,fps=c['width'],c['height'],c['fps']; duration=d['source']['duration_s']
    resources=[]; source_path=package/'assets/originals'/Path(d['source']['path']).name
    resources.append(copy_exact(d['source']['path'],source_path))
    graphics=[]
    for index,item in enumerate(prepared):
        path=package/f'assets/graphics/{index:02d}-{item["id"]}.png'
        resources.append(copy_exact(item['image'],path))
        resources.append(copy_exact(item['design']['path'],package/f'assets/artwork-originals/{index:02d}-{item["id"]}.png'))
        graphics.append(path)
    black=package/'assets/graphics/canvas-black.png'; Image.new('RGB',(w,h),'black').save(black)
    resources.append({'path':str(black),'sha256':sha256(black),'generated':'black canvas'})
    def tr(start,length):return draft.Timerange(round(start*1e6),round(length*1e6))
    tracks=[]
    with tempfile.TemporaryDirectory(prefix='calligraphy-native-') as temp:
        root=Path(temp)/'drafts';root.mkdir()
        df=draft.DraftFolder(str(root),user_data_path=str(Path(temp)/'User Data'))
        name='书法标题_'+d['id']; project=df.create_draft(name,w,h,fps=fps,allow_replace=False)
        bg=project.append_tracks([draft.TrackSpec(draft.TrackType.video,'画布黑底')])[0]
        project.add_segment(draft.VideoSegment(str(black),tr(0,duration),volume=0),track=bg)
        source=draft.VideoMaterial(str(source_path)); source.width=d['source']['metadata']['width'];source.height=d['source']['metadata']['height']
        main=project.append_tracks([draft.TrackSpec(draft.TrackType.video,'原片 · 静音 · 可回拉')])[0]
        geometry=d['source']['display_geometry']
        source_clip=draft.ClipSettings(scale_x=geometry['native_scale_x'],scale_y=geometry['native_scale_y'],
            transform_x=geometry['native_transform_x'],transform_y=geometry['native_transform_y'])
        project.add_segment(draft.VideoSegment(source,tr(0,duration),source_timerange=tr(d['source']['source_in_s'],duration),volume=0,clip_settings=source_clip),track=main)
        for item,path in zip(prepared,graphics):
            layer=item['design'];rows=item['rows'];a=rows[0]
            seg=draft.VideoSegment(str(path),tr(layer['start_s'],layer['layer_duration_s']),volume=0,
                clip_settings=draft.ClipSettings(transform_x=2*a['dx_px']/w,transform_y=-2*a['dy_px']/h,
                    scale_x=a['scale'],scale_y=a['scale'],rotation=a['rotation_deg'],alpha=a['opacity']))
            mapping=[(draft.KeyframeProperty.position_x,'dx_px',2/w),(draft.KeyframeProperty.position_y,'dy_px',-2/h),
                     (draft.KeyframeProperty.uniform_scale,'scale',1),(draft.KeyframeProperty.rotation,'rotation_deg',1),
                     (draft.KeyframeProperty.alpha,'opacity',1)]
            varying=[]
            for prop,key,multiplier in mapping:
                if any(abs(r[key]-a[key])>1e-10 for r in rows[1:]):
                    varying.append(key)
                    for r in rows:seg.add_keyframe(prop,round(r['time_s']*1e6),r[key]*multiplier)
            track=project.append_tracks([draft.TrackSpec(draft.TrackType.video,'书法标题 PNG' if item['id']=='title' else '小配件 · '+item['id'])])[0]
            project.add_segment(seg,track=track)
            tracks.append({'id':item['id'],'segment_id':seg.segment_id,'material_id':seg.material_id,
                'native_editable_properties':varying,'sample_count':len(rows),'artwork_characters_editable':False,
                'native_image_position_scale_alpha_editable':True,'native_rotation_editable':True,
                'inner_artwork_baked':True})
        project.save()
        for p in (root/name).iterdir():
            if p.is_file():shutil.copy2(p,package/p.name)
    content=read(package/'draft_content.json');meta=read(package/'draft_meta_info.json')
    meta.update(draft_fold_path=str(package),draft_root_path=str(package.parent),draft_name=name)
    encode(package,content,meta,cfg)
    paths={}
    def collect(obj):
        if isinstance(obj,dict):
            for x in obj.values():collect(x)
        elif isinstance(obj,list):
            for x in obj:collect(x)
        elif isinstance(obj,str):
            try:
                p=Path(obj)
                if p.is_absolute() and p.exists() and p.resolve().is_relative_to(package):paths[obj]=p.resolve().relative_to(package).as_posix()
            except (ValueError,OSError):pass
    collect(content)
    write(package/'portable-manifest.json',{'schema_version':'1.0','original_root':str(package),'media_paths':paths,'font_path':None,
        'note':'Rebase current editable draft; original artwork and independent image tracks are preserved.'})
    shutil.copy2(ROOT/'scripts/open-package.ps1',package/'open-package.ps1')
    (package/'修复并打开工程.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-package.ps1"\r\n',encoding='ascii')
    write(package/'design.json',d)
    report={'draft_path':str(package),'draft_id':content['id'],'encrypted_roundtrip':True,'ui_verified':False,
        'registered':False,'original_audio_muted':True,'source_hashes_verified':True,'original_video_baked':False,
        'resources':resources,'tracks':tracks,'layer_count':len(prepared)+2,'shared_motion_table':True,
        'source_display_geometry':d['source']['display_geometry'],
        'equivalence':'Same per-project-frame geometry/alpha samples. Native image/color rendering awaits editor verification.',
        'gaps':['No Jianying UI open/play/edit/save/export check has been performed.',
                'PNG artwork characters are baked pixels; independent position, scale and opacity remain editable.',
                'Output BT.709 delivery tags are not proof of unknown source camera colorimetry.']}
    write(package/'native-report.json',report)
    return report


def render_case(design_path,output,cfg,resume=False):
    document=read(design_path);d=validate_design(document,Path(design_path).resolve().parent,cfg)
    fingerprint=hashlib.sha256(json.dumps({'pipeline_version':PIPELINE_VERSION,'design':d},ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
    output=Path(output).resolve();state_path=output/'case-state.json'
    if output.exists():
        if not resume or not state_path.exists():raise ValueError('Output exists; use a new directory or matching --resume')
        state=read(state_path)
        if state['input_fingerprint']!=fingerprint:raise ValueError('Input changed; resume refused')
        if (output/'case-report.json').exists():
            previous=read(output/'case-report.json')
            if Path(previous['video']['path']).exists() and sha256(previous['video']['path'])!=previous['video']['sha256']:
                raise ValueError('Existing video changed; refusing automatic overwrite')
    else:
        output.mkdir(parents=True)
        state={'input_fingerprint':fingerprint,'status':'started','started_at_unix':time.time()}
    write(state_path,state);write(output/'resolved-design.json',d)
    try:
        prepared=prepare(d,output);state['stage']='resources_prepared';write(state_path,state)
        native=build_native(d,prepared,output,cfg);state['stage']='native_codec_verified';write(state_path,state)
        video=render_mp4(d,prepared,output,cfg);state['stage']='mp4_decode_verified';write(state_path,state)
        for item in [d['source'],*d['layers']]:
            if sha256(item['path'])!=item['sha256']:raise ValueError('Original source/artwork changed during processing')
        # These technical stills are for the primary agent's actual visual QA.
        stills=[];title=d['layers'][0];tm=title['motion']
        qa_times=[title['start_s']+tm['stagger_s']+tm['enter_s']/2,
                  (title['start_s']+tm['stagger_s']+tm['enter_s']+title['end_s']-tm['exit_s'])/2,
                  title['end_s']-tm['exit_s']/2]
        qa_times=[min(d['source']['duration_s']-1/d['canvas']['fps'],round(t*d['canvas']['fps'])/d['canvas']['fps']) for t in qa_times]
        for index,t in enumerate(qa_times):
            path=output/f'qa-{index}-{round(t*1e6):07d}.png'
            if not path.exists():run([cfg['ffmpeg'],'-v','error','-ss',str(t),'-i',video['path'],'-frames:v','1','-n',path])
            stills.append(str(path))
        report={'schema_version':'title-intro-report.1.0','pipeline_version':PIPELINE_VERSION,'id':d['id'],'title_text':d.get('title_text'),
            'input_fingerprint':fingerprint,'video':video,'native':native,'stills':stills,'stills_time_s':qa_times,
            'source_sha256':d['source']['sha256'],'source_original_unchanged':True,
            'source_color_metadata':d['source']['metadata'],'source_colorimetry_verified':False,
            'source_color_handling':'FFmpeg decodes recorded tags/defaults; untagged source interpretation remains unverified. Final RGB→YUV matrix is explicitly BT.709 limited-range.',
            'artwork_input_space':'explicit sRGB declaration; separate BT.709 conversion bridge with alpha preserved',
            'artwork_sources_preserved':True,'motion_source':'per-layer motion-table.json, consumed by both renderers',
            'audio_auditioned':False,'ui_verified':False,'visual_reviewed':False,'design_judgement':d.get('design',{})}
        write(output/'case-report.json',report);state.update(status='complete',stage='complete',finished_at_unix=time.time());write(state_path,state)
        return report
    except Exception as exc:
        state.update(status='failed',error=str(exc));write(state_path,state);raise


def synthetic_self_test(output,cfg):
    root=Path(output).resolve()
    if root.exists():raise ValueError('Synthetic self-test needs a new directory')
    root.mkdir(parents=True)
    source=root/'synthetic-source.mp4'
    run([cfg['ffmpeg'],'-v','error','-f','lavfi','-i','testsrc2=size=854x480:rate=60:duration=4',
         '-vf','setsar=2/1','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-n',source])
    art=Image.new('RGBA',(480,200));dr=ImageDraw.Draw(art)
    dr.line([(30,160),(140,40),(220,150),(340,30),(440,130)],fill='#F3E6CC',width=20)
    art.save(root/'synthetic-brush.png')
    accessory=Image.new('RGBA',(80,80));dr=ImageDraw.Draw(accessory);dr.rectangle((12,12,68,68),outline='#AB3A2F',width=5)
    accessory.save(root/'synthetic-seal.png')
    d={'schema_version':'title-intro.1.0','id':'synthetic','title_text':'synthetic strokes, not generated calligraphy',
        'source':{'path':str(source),'source_in_s':0,'duration_s':4},'canvas':{'width':854,'height':480,'fps':60},
        'title':{'path':str(root/'synthetic-brush.png'),'x_px':150,'y_px':160,'width_px':480,'start_s':.25,'end_s':3.8,
                 'motion':{'type':'curved_path','enter_s':.8,'exit_s':.45,'cubic_bezier_points_px':[[-90,35],[-45,-50],[30,-25],[0,0]],
                           'settle_s':.25,'overshoot_px':5,'from_rotation_deg':-8,'rotation_deg':0,'overshoot_rotation_deg':1}},
        'accessories':[{'id':'seal','path':str(root/'synthetic-seal.png'),'x_px':650,'y_px':300,'width_px':60,
                        'start_s':.25,'end_s':3.8,'motion':{'type':'rotate_settle','stagger_s':.2,'dx_px':0,'dy_px':8,
                            'from_rotation_deg':-14,'rotation_deg':0,'overshoot_rotation_deg':3,'settle_s':.3}}],
        'design':{'fixture':True,'user_media_used':False}}
    write(root/'design.json',d)
    result=render_case(root/'design.json',root/'rendered',cfg)
    # Read actual encrypted content and compare all geometric properties to
    # the shared project-frame samples, rather than trusting a report boolean.
    from pyJianYingDraft.draft_codec import load_json_object_with_codec
    content,encrypted=load_json_object_with_codec(root/'rendered/jianying/draft_content.json',content_codec=codec(cfg))
    if not encrypted:raise AssertionError('Native draft is not encrypted')
    resolved=read(root/'rendered/resolved-design.json')
    geometry=resolved['source']['display_geometry']
    if geometry['raster_width']!=854 or geometry['raster_height']!=240 or geometry['raster_y']!=120:
        raise AssertionError('Measured SAR2:1 display contain is incorrect')
    main_segment=content['tracks'][1]['segments'][0]
    if abs(main_segment['clip']['scale']['y']-.5)>1e-9:
        raise AssertionError('Native source SAR fit correction differs')
    frame=root/'sar-before-title.png'
    run([cfg['ffmpeg'],'-v','error','-ss','0.05','-i',result['video']['path'],'-frames:v','1','-n',frame])
    with Image.open(frame) as check:
        # Before title entry, black margins must occupy the top/bottom of the
        # 2:1-pixel synthetic source's 854x240 display region.
        if max(check.getpixel((400,20)))>5 or max(check.getpixel((400,450)))>5:
            raise AssertionError('Actual encoded output ignored source SAR display fitting')
        if max(check.getpixel((400,220)))<50:
            raise AssertionError('Actual SAR image region is unexpectedly black')
    by_id={x['id']:x for trk in content['tracks'] for x in trk['segments']}
    properties={'KFTypePositionX':('dx_px',2/854),'KFTypePositionY':('dy_px',-2/480),
                'KFTypeRotation':('rotation_deg',1),'KFTypeScaleX':('scale',1),'KFTypeAlpha':('opacity',1)}
    for info,layer in zip(result['native']['tracks'],resolved['layers']):
        rows=motion_table(layer,60);segment=by_id[info['segment_id']]
        for curve in segment['common_keyframes']:
            key,multiplier=properties[curve['property_type']]
            if len(curve['keyframe_list'])!=len(rows):raise AssertionError('Native keyframe count changed')
            for k,row in zip(curve['keyframe_list'],rows):
                if k['time_offset']!=round(row['time_s']*1e6) or abs(k['values'][0]-row[key]*multiplier)>1e-9:
                    raise AssertionError('Native keyframe differs from shared motion table')
    # Resume must preserve files; a modified design must be rejected.
    again=render_case(root/'design.json',root/'rendered',cfg,resume=True)
    if again['video']['sha256']!=result['video']['sha256']:raise AssertionError('Resume changed the video')
    changed=deepcopy(d);changed['title']['x_px']+=1;write(root/'changed-design.json',changed)
    try:render_case(root/'changed-design.json',root/'rendered',cfg,resume=True)
    except ValueError as exc:
        if 'Input changed' not in str(exc):raise
    else:raise AssertionError('Changed design was not rejected')
    # Range/alpha/native codec tests use only synthetic resources.
    invalid=deepcopy(d);invalid['source']['source_in_s']=3
    try:validate_design(invalid,root,cfg)
    except ValueError:pass
    else:raise AssertionError('Source overrun was not rejected')
    write(root/'self-test-report.json',{'passed':True,'synthetic_only':True,'frame_count':240,
        'native_encrypted_roundtrip':True,'resume_preserved_sha':True,'changed_design_rejected':True,
        'source_overrun_rejected':True,'native_all_motion_samples_compared':True,
        'actual_non_square_sar_fit_tested':'2:1 SAR retained in original source; FFmpeg display region measured 854x240, native y scale .5 encoded/read back',
        'native_rotation_convention':'Actual library documents clockwise degrees; encrypted rotation values compared. Editor rendering remains unverified.',
        'ui_verified':False,'audio_auditioned':False})
    return {'passed':True,'directory':str(root),'video':result['video']['path'],'native':result['native']['draft_path']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Machine config; defaults to package-local config or VIDEO_EDIT_CONFIG')
    sub=parser.add_subparsers(dest='command',required=True)
    render=sub.add_parser('render');render.add_argument('--design',required=True);render.add_argument('--output',required=True);render.add_argument('--resume',action='store_true')
    validate=sub.add_parser('validate');validate.add_argument('--design',required=True)
    test=sub.add_parser('synthetic-self-test');test.add_argument('--output',required=True)
    args=parser.parse_args();cfg=load_config(args.config)
    if args.command=='validate':
        design=validate_design(read(args.design),Path(args.design).resolve().parent,cfg)
        result={'valid':True,'pipeline_version':PIPELINE_VERSION,'design':design,
                'human_visual_review':'pending','ui_verified':False}
    elif args.command=='synthetic-self-test':
        result=synthetic_self_test(args.output,cfg)
    else:
        result=render_case(args.design,args.output,cfg,args.resume)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'error':str(exc),'type':type(exc).__name__},ensure_ascii=False),file=sys.stderr)
        raise

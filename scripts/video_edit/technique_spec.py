"""Typed, local technique assets: timeline layers -> deterministic FFmpeg graph.

This is separate from the story/edit-plan schema. Rendered technique assets must
be reviewed and added to that plan's inventory; a technique name never executes
an effect by itself. No proprietary effect IDs or arbitrary filter expressions.
"""
from __future__ import annotations
from copy import deepcopy
import math
import json
import os
from pathlib import Path
import re
from .common import EditError, IMAGE_EXTS, probe, run, read, write, sha256, filter_script_args

SCHEMA = 'technique.2.0'
TOP = {'schema_version','canvas','layers','input_space','provenance','purpose'}
CANVAS = {'width','height','fps','duration','background','background_opacity'}
LAYER = {'id','source','start','duration','source_in','speed','speed_curve','freeze_at','reverse',
         'x','y','scale','rotation','opacity','keyframes','easing','blend','mask','key',
         'fade_in','fade_out','crop','color','purpose'}
SOURCE = {'kind','path','color','text','font_path','font_size_px','stroke_px','stroke_color',
          'glow_radius_px','glow_opacity','loop'}
TRANSFORMS = {'x':(-4,4,0),'y':(-4,4,0),'scale':(.01,8,1),
              'rotation':(-3600,3600,0),'opacity':(0,1,1)}
MASK = {'type','x','y','width','height','rotation','feather_px','invert','progress','path',
        'mode','source_in','loop','text','font_path','font_size_px'}
BLENDS = {'normal','screen','multiply','addition','lighten','darken'}

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def resolve(value,base):
    p=Path(value).expanduser()
    return (p if p.is_absolute() else Path(base)/p).resolve()

def _fields(obj,allowed,where,errors):
    if not isinstance(obj,dict):
        errors.append({'at':where,'message':'需要对象'});return False
    if set(obj)-allowed:
        errors.append({'at':where,'message':'未知参数：'+', '.join(sorted(set(obj)-allowed))})
    return True

def _number(value,lo,hi,where,errors):
    if not finite(value) or not lo<=value<=hi:
        errors.append({'at':where,'message':f'需要范围{lo}–{hi}内的有限数值'});return False
    return True

def _frame(value,fps,where,errors):
    if finite(value) and abs(value*fps-round(value*fps))>.002:
        errors.append({'at':where,'message':'时间须对齐项目帧率'})

def _hex(value):return isinstance(value,str) and re.fullmatch(r'#[0-9a-fA-F]{6}',value)

def validate(spec,base,cfg,inspect_files=True):
    errors=[];warnings=[];assets={}
    if not _fields(spec,TOP,'spec',errors):return {'valid':False,'errors':errors,'warnings':warnings}
    if spec.get('schema_version')!=SCHEMA:errors.append({'at':'schema_version','message':f'需要{SCHEMA}'})
    if spec.get('input_space')!='bt709_sdr':errors.append({'at':'input_space','message':'目前技巧资产仅支持明确声明的BT.709 SDR；不得猜测未知或Log输入'})
    canvas=spec.get('canvas',{})
    if not _fields(canvas,CANVAS,'canvas',errors):return {'valid':False,'errors':errors,'warnings':warnings}
    for k,lo,hi in [('width',2,7680),('height',2,7680)]:
        if not isinstance(canvas.get(k),int) or isinstance(canvas[k],bool) or not lo<=canvas[k]<=hi or canvas[k]%2:
            errors.append({'at':'canvas.'+k,'message':'需要2–7680的偶数整数'})
    fps=canvas.get('fps');duration=canvas.get('duration')
    if fps not in (24,25,30,50,60) or isinstance(fps,bool):errors.append({'at':'canvas.fps','message':'支持24/25/30/50/60 fps'})
    if not _number(duration,.001,600,'canvas.duration',errors):return {'valid':False,'errors':errors,'warnings':warnings}
    if errors:return {'valid':False,'errors':errors,'warnings':warnings}
    _frame(duration,fps,'canvas.duration',errors)
    if canvas['width']*canvas['height']>16777216:errors.append({'at':'canvas','message':'技巧资产画布超过16,777,216像素预算'})
    if not _hex(canvas.get('background','#000000')):errors.append({'at':'canvas.background','message':'需要#RRGGBB'})
    _number(canvas.get('background_opacity',0),0,1,'canvas.background_opacity',errors)
    layers=spec.get('layers')
    if not isinstance(layers,list) or not 1<=len(layers)<=64:
        errors.append({'at':'layers','message':'需要1–64个明确图层'});return {'valid':False,'errors':errors,'warnings':warnings}
    ids=set()
    for i,layer in enumerate(layers):
        where=f'layers[{i}]'
        if not _fields(layer,LAYER,where,errors):continue
        ident=layer.get('id')
        if not isinstance(ident,str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}',ident) or ident in ids:
            errors.append({'at':where+'.id','message':'图层编号需为唯一ASCII标识符'})
        ids.add(str(ident))
        start=layer.get('start',0);length=layer.get('duration',duration)
        valid=_number(start,0,duration,where+'.start',errors)&_number(length,1/fps,duration,where+'.duration',errors)
        if valid:
            _frame(start,fps,where+'.start',errors);_frame(length,fps,where+'.duration',errors)
            if start+length>duration+1e-8:errors.append({'at':where,'message':'图层越过时间线终点'})
        else:
            continue
        for name,(lo,hi,default) in TRANSFORMS.items():_number(layer.get(name,default),lo,hi,where+'.'+name,errors)
        if layer.get('easing','linear') not in ('linear','smoothstep'):errors.append({'at':where+'.easing','message':'仅支持linear/smoothstep'})
        if not isinstance(layer.get('blend','normal'),str) or layer.get('blend','normal') not in BLENDS:errors.append({'at':where+'.blend','message':'不支持的混合模式'})
        if 'reverse' in layer and not isinstance(layer['reverse'],bool):errors.append({'at':where+'.reverse','message':'需要布尔值'})
        for name in ('fade_in','fade_out'):
            _number(layer.get(name,0),0,length if finite(length) else 0,where+'.'+name,errors)
        if 'crop' in layer:
            crop=layer['crop']
            if not isinstance(crop,list) or len(crop)!=4 or any(not finite(v) for v in crop) or any(v<0 for v in crop[:2]) or any(v<=0 for v in crop[2:]) or crop[0]+crop[2]>1+1e-8 or crop[1]+crop[3]>1+1e-8:
                errors.append({'at':where+'.crop','message':'需要源画面归一化[x,y,width,height]，完全位于0–1范围内'})
        keys=layer.get('keyframes')
        if keys is not None:
            previous=-1
            if not isinstance(keys,list) or not keys or any(not isinstance(k,dict) for k in keys):errors.append({'at':where+'.keyframes','message':'需要非空关键帧对象数组'})
            else:
                for j,key in enumerate(keys):
                    at=f'{where}.keyframes[{j}]'
                    if not _fields(key,{'time',*TRANSFORMS},at,errors):continue
                    t=key.get('time')
                    if _number(t,0,max(0,length-1/fps) if finite(length) else 0,at+'.time',errors):
                        _frame(t,fps,at+'.time',errors)
                        if t<=previous:errors.append({'at':at,'message':'关键帧时间必须严格递增'})
                        previous=t
                    for name,(lo,hi,default) in TRANSFORMS.items():
                        if name in key:_number(key[name],lo,hi,at+'.'+name,errors)
                if keys[0].get('time')!=0 or not finite(keys[-1].get('time')) or abs(keys[-1]['time']-max(0,length-1/fps))>1e-8:
                    errors.append({'at':where+'.keyframes','message':'关键帧须覆盖首帧到最后可见帧duration−1/fps'})
        src=layer.get('source',{})
        if not _fields(src,SOURCE,where+'.source',errors):continue
        kind=src.get('kind','asset')
        if kind not in ('asset','text','solid'):errors.append({'at':where+'.source.kind','message':'需要asset/text/solid'})
        allowed_source={'asset':{'kind','path','loop'},'solid':{'kind','color'},
            'text':{'kind','text','font_path','font_size_px','color','stroke_px','stroke_color','glow_radius_px','glow_opacity'}}
        if isinstance(kind,str) and kind in allowed_source and set(src)-allowed_source[kind]:
            errors.append({'at':where+'.source','message':'此素材类型不能使用参数：'+', '.join(sorted(set(src)-allowed_source[kind]))})
        if 'loop' in src and not isinstance(src['loop'],bool):errors.append({'at':where+'.source.loop','message':'需要布尔值'})
        _number(layer.get('source_in',0),0,864000,where+'.source_in',errors)
        _number(layer.get('speed',1),.1,10,where+'.speed',errors)
        if 'freeze_at' in layer:_number(layer['freeze_at'],0,864000,where+'.freeze_at',errors)
        if 'freeze_at' in layer and ('speed_curve' in layer or layer.get('speed',1)!=1 or layer.get('reverse')):
            errors.append({'at':where,'message':'定格不能同时使用变速或倒放；请用独立图层/片段组合'})
        if 'freeze_at' in layer and layer.get('source_in',0)!=0:errors.append({'at':where+'.freeze_at','message':'freeze_at是原片绝对秒数，不能再叠加source_in'})
        if 'speed_curve' in layer:
            from .retiming import validate_curve
            try:validate_curve(layer['speed_curve'],length,fps)
            except (ValueError,TypeError) as exc:errors.append({'at':where+'.speed_curve','message':str(exc)})
            if layer.get('speed',1)!=1:errors.append({'at':where+'.speed_curve','message':'曲线与恒速不能同时指定'})
            if layer.get('reverse'):errors.append({'at':where+'.speed_curve','message':'曲线与倒放请分为两个技巧资产步骤'})
        if kind in ('text','solid') and any(k in layer for k in ('speed_curve','freeze_at','reverse')):
            errors.append({'at':where,'message':'文字/纯色不支持视频源时间操作'})
        if kind in ('text','solid') and (layer.get('source_in',0)!=0 or layer.get('speed',1)!=1):
            errors.append({'at':where,'message':'文字/纯色不支持源入点或变速'})
        if kind=='solid' and 'crop' in layer:errors.append({'at':where+'.crop','message':'纯色没有源裁剪；使用几何蒙版限定区域'})
        if kind in ('text','solid') and not _hex(src.get('color','#FFFFFF')):errors.append({'at':where+'.source.color','message':'需要#RRGGBB'})
        if kind=='text':
            if not isinstance(src.get('text'),str) or not 1<=len(src['text'])<=500:errors.append({'at':where+'.source.text','message':'需要1–500字符文字'})
            for name,lo,hi,default in [('font_size_px',1,2048,64),('stroke_px',0,128,0),('glow_radius_px',0,256,0),('glow_opacity',0,1,.6)]:_number(src.get(name,default),lo,hi,where+'.source.'+name,errors)
            for name in ('font_size_px','stroke_px'):
                if name in src and (not isinstance(src[name],int) or isinstance(src[name],bool)):errors.append({'at':where+'.source.'+name,'message':'需要整数像素'})
            if not _hex(src.get('stroke_color','#000000')):errors.append({'at':where+'.source.stroke_color','message':'需要#RRGGBB'})
            font=resolve(src.get('font_path',cfg.get('font_path') or ''),base)
            if not font.is_file():errors.append({'at':where+'.source.font_path','message':'字体文件不存在'})
        if kind=='asset':
            if not isinstance(src.get('path'),str) or not src['path'].strip():errors.append({'at':where+'.source.path','message':'需要本地素材路径'})
            else:
                p=resolve(src['path'],base)
                if not p.is_file():errors.append({'at':where+'.source.path','message':'素材不存在'})
                elif inspect_files:
                    try:
                        m=probe(p,cfg);assets[ident]={'path':str(p),'metadata':m,'kind':'image' if p.suffix.lower() in IMAGE_EXTS else 'video'}
                        if assets[ident]['kind']=='image' and (any(k in layer for k in ('speed_curve','freeze_at','reverse')) or layer.get('source_in',0)!=0 or layer.get('speed',1)!=1 or src.get('loop')):
                            errors.append({'at':where+'.source','message':'静态图片不接受视频源时间操作或显式循环'})
                        if (m.get('color_transfer') not in (None,'','unknown','unspecified','bt709')
                            or m.get('color_primaries') not in (None,'','unknown','unspecified','bt709')
                            or m.get('color_space') not in (None,'','unknown','unspecified','bt709','gbr')):
                            errors.append({'at':where+'.source','message':'技巧编译器当前不接受HDR、Log或非BT.709输入；先做明确的色彩转换'})
                        if assets[ident]['kind']=='video' and valid:
                            from .retiming import source_span
                            span=source_span(layer['speed_curve']) if 'speed_curve' in layer else length*layer.get('speed',1)
                            source_end=layer.get('source_in',0)+span
                            if 'freeze_at' in layer:
                                if layer['freeze_at']>=m['duration']:errors.append({'at':where+'.freeze_at','message':'定格时间超出视频'})
                            elif not src.get('loop') and source_end>m['duration']+.002:errors.append({'at':where+'.source','message':'播放区间超出原片；循环须显式声明'})
                    except (EditError,ValueError,KeyError,TypeError) as exc:errors.append({'at':where+'.source','message':str(exc)})
        if 'key' in layer:
            key=layer['key']
            if _fields(key,{'color','similarity','softness'},where+'.key',errors):
                if not _hex(key.get('color')):errors.append({'at':where+'.key.color','message':'需要#RRGGBB'})
                _number(key.get('similarity',.1),.01,1,where+'.key.similarity',errors)
                _number(key.get('softness',.1),0,1,where+'.key.softness',errors)
        if 'mask' in layer:
            mask=layer['mask']
            if _fields(mask,MASK,where+'.mask',errors):
                typ=mask.get('type')
                if typ not in ('rect','ellipse','linear','text','asset'):errors.append({'at':where+'.mask.type','message':'需要rect/ellipse/linear/text/asset'})
                common_mask={'type','feather_px','invert'}
                by_type={'rect':{'x','y','width','height','rotation'},'ellipse':{'x','y','width','height','rotation'},'linear':{'rotation','progress'},'text':{'text','font_path','font_size_px'},'asset':{'path','mode','source_in','loop'}}
                if isinstance(typ,str) and typ in by_type and set(mask)-common_mask-by_type[typ]:errors.append({'at':where+'.mask','message':'此蒙版类型包含不适用参数'})
                for name,lo,hi,default in [('x',-1,1,0),('y',-1,1,0),('width',.001,1,1),('height',.001,1,1),('rotation',-3600,3600,0),('feather_px',0,512,0),('source_in',0,864000,0)]:_number(mask.get(name,default),lo,hi,where+'.mask.'+name,errors)
                if not isinstance(mask.get('invert',False),bool):errors.append({'at':where+'.mask.invert','message':'需要布尔值'})
                if 'loop' in mask and not isinstance(mask['loop'],bool):errors.append({'at':where+'.mask.loop','message':'需要布尔值'})
                if mask.get('mode','luma') not in ('luma','alpha'):errors.append({'at':where+'.mask.mode','message':'需要luma/alpha'})
                if typ=='asset':
                    if not isinstance(mask.get('path'),str) or not resolve(mask.get('path',''),base).is_file():errors.append({'at':where+'.mask.path','message':'蒙版素材不存在'})
                    elif inspect_files:
                        try:
                            mask_path=resolve(mask['path'],base);mask_meta=probe(mask_path,cfg)
                            if mask_path.suffix.lower() not in IMAGE_EXTS and not mask.get('loop') and mask.get('source_in',0)+length>mask_meta['duration']+.002:
                                errors.append({'at':where+'.mask','message':'蒙版视频时长不足；循环须显式声明'})
                            if mask.get('mode')=='alpha' and not re.match(r'^(rgba|argb|bgra|abgr|yuva|gbrap|ya\d)',mask_meta.get('pix_fmt') or ''):
                                errors.append({'at':where+'.mask.mode','message':'蒙版素材没有可提取的alpha通道'})
                        except (EditError,ValueError,KeyError,TypeError) as exc:errors.append({'at':where+'.mask','message':str(exc)})
                if typ=='text' and (not isinstance(mask.get('text'),str) or not 1<=len(mask['text'])<=500):errors.append({'at':where+'.mask.text','message':'需要1–500字符文字'})
                if typ=='text':
                    _number(mask.get('font_size_px',64),1,2048,where+'.mask.font_size_px',errors)
                    if 'font_size_px' in mask and (not isinstance(mask['font_size_px'],int) or isinstance(mask['font_size_px'],bool)):errors.append({'at':where+'.mask.font_size_px','message':'需要整数像素'})
                    if not resolve(mask.get('font_path',cfg.get('font_path') or ''),base).is_file():errors.append({'at':where+'.mask.font_path','message':'蒙版字体文件不存在'})
                progress=mask.get('progress',1)
                if isinstance(progress,list):
                    if not progress or any(not isinstance(k,dict) or set(k)!={'time','value'} or not finite(k['time']) or not finite(k['value']) or not 0<=k['value']<=1 for k in progress):errors.append({'at':where+'.mask.progress','message':'进度关键帧需要time/value，value为0–1'})
                    elif progress[0]['time']!=0 or any(b['time']<=a['time'] for a,b in zip(progress,progress[1:])) or progress[-1]['time']>length:
                        errors.append({'at':where+'.mask.progress','message':'进度关键帧须从0开始递增且位于图层时长内'})
                else:_number(progress,0,1,where+'.mask.progress',errors)
        if 'color' in layer:
            from .color import normalize
            try:normalize(layer['color'])
            except (EditError,ValueError,TypeError) as exc:errors.append({'at':where+'.color','message':str(exc)})
    if any(layer.get('reverse') for layer in layers if isinstance(layer,dict)):warnings.append('倒放需要FFmpeg缓冲完整片段，长片段请先限定源区间。')
    return {'valid':not errors,'errors':errors,'warnings':warnings,'assets':assets}

def tween(keys,name,default,variable='t',easing='linear'):
    """Held endpoints, layer-local seconds; property omissions inherit defaults."""
    if not keys:return f'{default:.12g}'
    values=[];current=default
    for key in keys:
        current=key.get(name,current);values.append((key['time'],current))
    expr=f'{values[-1][1]:.12g}'
    for (a,va),(b,vb) in reversed(list(zip(values,values[1:]))):
        u=f'clip(({variable}-{a:.12g})/{b-a:.12g},0,1)'
        if easing=='smoothstep':u=f'({u})*({u})*(3-2*({u}))'
        val=f'{va:.12g}+({vb-va:.12g})*({u})'
        expr=f'if(lt({variable},{b:.12g}),{val},{expr})'
    return expr

def _ffcolor(value,opacity=1):return f'0x{value[1:]}@{opacity:.12g}'

def _add_input(cmd,path,image=False,loop=False,seek=0):
    if image:cmd+=['-loop','1']
    elif loop:cmd+=['-stream_loop','-1']
    if seek:cmd+=['-ss',f'{seek:.12g}']
    cmd+=['-i',str(path)]

def compile_spec(spec,base,cfg,work):
    result=validate(spec,base,cfg,inspect_files=True)
    if not result['valid']:raise EditError('TECHNIQUE_INVALID','技巧参数未通过校验。',result)
    work=Path(work).resolve();work.mkdir(parents=True,exist_ok=True)
    c=spec['canvas'];w,h,fps,total=c['width'],c['height'],c['fps'],c['duration']
    cmd=[cfg['ffmpeg'],'-hide_banner','-v','error','-nostdin'];filters=[];inputs=0;resources=[]
    def label(prefix):return f'{prefix}{len(filters)}'
    def push(expression):filters.append(expression)
    def raster(source,path):
        from .text_raster import render_text
        font=resolve(source.get('font_path',cfg.get('font_path') or ''),base)
        image=render_text(canvas_size=(w,h),text=source['text'],font_path=font,
            font_size_px=source.get('font_size_px',64),color=source.get('color','#FFFFFF'),
            stroke_px=source.get('stroke_px',0),stroke_color=source.get('stroke_color','#000000'),
            glow_radius_px=source.get('glow_radius_px',0),glow_opacity=source.get('glow_opacity',.6))
        image.save(path);resources.append({'kind':'generated_text','path':str(path),'sha256':sha256(path),'font_sha256':sha256(font)})
    push(f'color=c={_ffcolor(c.get("background","#000000"),c.get("background_opacity",0))}:s={w}x{h}:r={fps}:d={total},format=rgba[base]');previous='base'
    for n,layer in enumerate(spec['layers']):
        ident=layer['id'];source=layer['source'];kind=source.get('kind','asset');start=layer.get('start',0);length=layer.get('duration',total)
        tag=f'l{n}';chain=[]
        if kind=='solid':
            push(f'color=c={_ffcolor(source.get("color","#FFFFFF"))}:s={w}x{h}:r={fps}:d={length},format=rgba[{tag}source]');current=tag+'source'
        else:
            if kind=='text':
                path=work/f'text-{n:03}.png';raster(source,path);image=True
            else:
                path=resolve(source['path'],base);image=path.suffix.lower() in IMAGE_EXTS
                resources.append({'kind':'input','path':str(path),'fingerprint':{'size':path.stat().st_size,'mtime_ns':path.stat().st_mtime_ns},'sha256':sha256(path)})
            seek=layer.get('freeze_at',layer.get('source_in',0))
            _add_input(cmd,path,image,source.get('loop',False),seek if not image else 0);index=inputs;inputs+=1
            chain=['setpts=PTS-STARTPTS']
            if 'freeze_at' in layer:chain+=['trim=end_frame=1',f'tpad=stop_mode=clone:stop_duration={length}']
            elif 'speed_curve' in layer:
                from .retiming import source_span,setpts_expression
                chain += [f'trim=duration={source_span(layer["speed_curve"]):.12g}','settb=AVTB',f"setpts='{setpts_expression(layer['speed_curve'])}'"]
            else:
                chain += [f'trim=duration={length*layer.get("speed",1):.12g}']
                if layer.get('reverse'):chain+=['reverse','setpts=PTS-STARTPTS']
                chain += [f'setpts=PTS/{layer.get("speed",1):.12g}']
            chain += [f'fps={fps}',f'tpad=stop_mode=clone:stop_duration={1/fps:.12g}',f'trim=end_frame={round(length*fps)}','setpts=PTS-STARTPTS','format=rgba']
            if layer.get('crop'):
                x,y,cw,ch=layer['crop'];chain += [f'crop=iw*{cw}:ih*{ch}:iw*{x}:ih*{y}']
            # Normalize display geometry before contain. Forcing SAR=1 only
            # after fitting coded pixels silently stretches anamorphic media.
            chain += ["scale=w='max(2,round(iw*if(gt(sar,0),sar,1)))':h=ih:flags=lanczos",'setsar=1',f'scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos',f'pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0','setsar=1']
            current=tag+'source';push(f'[{index}:v]'+','.join(chain)+f'[{current}]')
        if layer.get('color'):
            from .color import input_color_filter
            color_filter=input_color_filter({'color':layer['color']},layer,{'source_metadata':{'color_transfer':'bt709','color_primaries':'bt709','color_space':'bt709'}},work)
            if color_filter:
                dest=label(tag+'grade');push(f'[{current}]'+color_filter.rstrip(',')+f'[{dest}]');current=dest
        if layer.get('key'):
            key=layer['key'];dest=label(tag+'key');push(f'[{current}]colorkey=0x{key["color"][1:]}:{key.get("similarity",.1)}:{key.get("softness",.1)}[{dest}]');current=dest
        if layer.get('mask'):
            mask=layer['mask'];typ=mask['type'];matte=tag+'matte'
            if typ in ('asset','text'):
                if typ=='text':
                    path=work/f'mask-text-{n:03}.png';raster(mask,path);image=True
                else:path=resolve(mask['path'],base);image=path.suffix.lower() in IMAGE_EXTS
                _add_input(cmd,path,image,mask.get('loop',False),mask.get('source_in',0));index=inputs;inputs+=1
                mode='alphaextract' if typ=='text' or mask.get('mode')=='alpha' else 'format=gray'
                push(f'[{index}:v]setpts=PTS-STARTPTS,fps={fps},scale={w}:{h},trim=duration={length},format=rgba,{mode}[{matte}]')
                resources.append({'kind':'mask','path':str(path),'sha256':sha256(path)})
            else:
                angle=math.radians(mask.get('rotation',0));co,si=math.cos(angle),math.sin(angle)
                u=f'((X-{w*(mask.get("x",0)+1)/2:.12g})*{co:.12g}+(Y-{h*(1-mask.get("y",0))/2:.12g})*{si:.12g})'
                v=f'(-(X-{w*(mask.get("x",0)+1)/2:.12g})*{si:.12g}+(Y-{h*(1-mask.get("y",0))/2:.12g})*{co:.12g})'
                mw,mh=mask.get('width',1)*w,mask.get('height',1)*h
                if typ=='ellipse':distance=f'(sqrt(pow({u}/{mw/2:.12g},2)+pow({v}/{mh/2:.12g},2))-1)*{min(mw,mh)/2:.12g}'
                elif typ=='linear':
                    progress=mask.get('progress',1)
                    p=tween(progress,'value',0,'T') if isinstance(progress,list) else f'{progress:.12g}'
                    extent=abs(w*co)+abs(h*si)
                    distance=f'(X-W/2)*{co:.12g}+(Y-H/2)*{si:.12g}-(({p})-.5)*{extent:.12g}'
                else:distance=f'max(abs({u})-{mw/2:.12g},abs({v})-{mh/2:.12g})'
                feather=mask.get('feather_px',0)
                value=f'clip(.5-({distance})/{feather:.12g},0,1)' if feather else f'lte({distance},0)'
                push(f"color=white:s={w}x{h}:r={fps}:d={length},format=gray,geq=lum='255*({value})'[{matte}]")
            if typ in ('asset','text') and mask.get('feather_px',0):
                dest=label(tag+'soft');push(f'[{matte}]gblur=sigma={mask["feather_px"]}[{dest}]');matte=dest
            if mask.get('invert'):
                dest=label(tag+'invert');push(f'[{matte}]negate[{dest}]');matte=dest
            push(f'[{current}]split=2[{tag}rgb][{tag}alpha0]')
            push(f'[{tag}alpha0]alphaextract[{tag}alpha]')
            push(f'[{tag}alpha][{matte}]blend=all_mode=multiply:shortest=1[{tag}maskedalpha]')
            current=tag+'masked';push(f'[{tag}rgb][{tag}maskedalpha]alphamerge[{current}]')
        keys=layer.get('keyframes');ease=layer.get('easing','linear')
        opacity=tween(keys,'opacity',layer.get('opacity',1),'T',ease)
        dest=label(tag+'opacity')
        if keys and any('opacity' in k for k in keys):
            push(f"[{current}]format=gbrap,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='alpha(X,Y)*({opacity})',format=rgba[{dest}]")
        else:push(f'[{current}]colorchannelmixer=aa={layer.get("opacity",1)}[{dest}]')
        current=dest
        for name in ('fade_in','fade_out'):
            if layer.get(name,0):
                dest=label(tag+'fade');out=name=='fade_out';at=length-layer[name] if out else 0
                push(f'[{current}]fade=t={"out" if out else "in"}:st={at}:d={layer[name]}:alpha=1[{dest}]');current=dest
        scale=tween(keys,'scale',layer.get('scale',1),'t',ease)
        rotation=tween(keys,'rotation',layer.get('rotation',0),'t',ease)
        dest=label(tag+'transform')
        push(f"[{current}]scale=w='max(2,round(iw*({scale})))':h='max(2,round(ih*({scale})))':eval=frame:flags=lanczos,rotate=angle='({rotation})*PI/180':ow=iw:oh=ih:c=none,setpts=PTS+{start:.12g}/TB[{dest}]");current=dest
        x=tween(keys,'x',layer.get('x',0),f'(t-{start:.12g})',ease)
        y=tween(keys,'y',layer.get('y',0),f'(t-{start:.12g})',ease)
        positioned=tag+'positioned'
        push(f'color=black@0:s={w}x{h}:r={fps}:d={total},format=rgba[{tag}transparent]')
        enable=f'gte(t,{start:.12g})*lt(t,{start+length:.12g})'
        push(f"[{tag}transparent][{current}]overlay=x='(W-w)/2+W/2*({x})':y='(H-h)/2-H/2*({y})':enable='{enable}':eval=frame:eof_action=pass:repeatlast=0:format=auto[{positioned}]")
        output=tag+'composite';blend=layer.get('blend','normal')
        if blend=='normal':push(f'[{previous}][{positioned}]overlay=0:0:eof_action=pass:repeatlast=0:format=auto[{output}]')
        else:
            # RGB blend with the positioned layer's alpha as a matte. Blending
            # an absent screen/multiply layer must leave the background intact.
            push(f'[{positioned}]split=2[{tag}blendfg][{tag}blendalpha0]')
            push(f'[{tag}blendalpha0]alphaextract[{tag}blendalpha]')
            push(f'[{previous}]split=2[{tag}blendbg][{tag}originalbg]')
            push(f'[{tag}blendfg][{tag}blendbg]blend=all_mode={blend}:shortest=1[{tag}blended]')
            push(f'[{tag}blended][{tag}blendalpha]alphamerge[{tag}blendedmasked]')
            push(f'[{tag}originalbg][{tag}blendedmasked]overlay=0:0:format=auto[{output}]')
        previous=output
    push(f'[{previous}]trim=end_frame={round(total*fps)},setpts=PTS-STARTPTS,format=argb[technique_out]')
    graph=work/'filtergraph.txt';graph.write_text(';\n'.join(filters),encoding='utf-8')
    command=[str(x) for x in cmd+['-filter_complex_threads','1',*filter_script_args(cfg['ffmpeg'],graph),'-map','[technique_out]','-an','-frames:v',round(total*fps),'-c:v','qtrle','-pix_fmt','argb','-r',fps,'-fps_mode','cfr','-n',work/'asset.partial.mov']]
    result={'schema_version':SCHEMA,'command':command,'filtergraph':str(graph),'resources':resources,
        'frames':round(total*fps),'canvas':c,'warnings':result['warnings'],
        'equivalence':'Typed mathematical composition; not a proprietary Jianying preset clone.',
        'audio':'silent technique asset; mix original reviewed audio in existing edit workflow'}
    write(work/'compiled.json',result);write(work/'technique-spec.json',spec)
    return result

def render(spec,base,cfg,output):
    output=Path(output).resolve()
    if output.exists():raise EditError('OUTPUT_EXISTS','技巧输出目录已存在，请使用新目录。')
    output.mkdir(parents=True)
    compiled=compile_spec(spec,base,cfg,output)
    try:
        run(compiled['command'],timeout=7200,cwd=output)
        partial=output/'asset.partial.mov';measured=probe(partial,cfg)
        frames=json.loads(run([cfg['ffprobe'],'-v','error','-select_streams','v:0','-show_entries','stream=nb_frames,pix_fmt','-of','json',partial]).stdout)['streams'][0]
        if int(frames.get('nb_frames',0))!=compiled['frames'] or (measured['width'],measured['height'])!=(spec['canvas']['width'],spec['canvas']['height']):
            raise EditError('TECHNIQUE_FRAME_MISMATCH','技巧资产帧数或画幅不符合参数。')
        run([cfg['ffmpeg'],'-v','error','-i',partial,'-f','null','-'],timeout=7200)
        for resource in compiled['resources']:
            if sha256(resource['path'])!=resource['sha256']:raise EditError('TECHNIQUE_SOURCE_CHANGED','素材或字体派生资源在渲染期间发生变化。',resource)
        target=output/'asset.mov';partial.rename(target)
        result={**compiled,'output':str(target),'sha256':sha256(target),'full_decode_verified':True,'measured':measured,
            'codec':'qtrle','lossless_video_compression':True,'alpha':True,'listened':False,
            'viewed_by_agent':False,'integration':'View the asset, add it to the film inventory, retain this spec/report, then continue the normal validate/export workflow.'}
        write(output/'technique-report.json',result);return result
    except BaseException as exc:
        write(output/'failure.json',{'error':repr(exc),'compiled':str(output/'compiled.json')});raise

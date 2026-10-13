"""Small, inspectable recipe builders; never select footage or invent music cues.

These emit the same typed graph that the validator and compiler consume. All
times are output seconds; frame quantization is explicit. External effect,
music, sticker and font assets remain the caller's responsibility.
"""
from __future__ import annotations
import math
from .common import EditError

def _base(width=1920,height=1080,fps=30,duration=3):
    if any(isinstance(v,bool) or not isinstance(v,int) or v<2 or v>7680 or v%2 for v in (width,height)) or width*height>16777216:raise ValueError('Canvas needs even 2..7680 pixel dimensions within the pixel budget')
    if isinstance(fps,bool) or fps not in (24,25,30,50,60):raise ValueError('fps needs 24/25/30/50/60')
    if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or not 1/fps<=duration<=600 or abs(duration*fps-round(duration*fps))>.002:raise ValueError('duration needs frame-aligned seconds, one frame..600 seconds')
    return {'schema_version':'technique.2.0','input_space':'bt709_sdr',
            'canvas':{'width':width,'height':height,'fps':fps,'duration':duration,'background_opacity':0},'layers':[]}

def _asset(path):return {'kind':'asset','path':path}
def _text(text,font_path,font_size_px,color='#FFFFFF',**kwargs):
    return {'kind':'text','text':text,'font_path':font_path,'font_size_px':font_size_px,'color':color,**kwargs}
def _last(spec):return spec['canvas']['duration']-1/spec['canvas']['fps']

def freeze(source,source_at,**canvas):
    spec=_base(**canvas);spec['layers']=[{'id':'freeze','source':_asset(source),'freeze_at':source_at}]
    return spec

def glow_title(text,font_path,font_size_px=96,color='#FFFFFF',glow_radius_px=12,**canvas):
    spec=_base(**canvas);spec['layers']=[{'id':'title','source':_text(text,font_path,font_size_px,color,glow_radius_px=glow_radius_px),
        'keyframes':[{'time':0,'opacity':0,'scale':.9},{'time':_last(spec),'opacity':1,'scale':1}],'easing':'smoothstep'}]
    return spec

def hollow_title(source,text,font_path,font_size_px=160,**canvas):
    spec=_base(**canvas);spec['layers']=[{'id':'text_picture','source':_asset(source),
        'mask':{'type':'text','text':text,'font_path':font_path,'font_size_px':font_size_px}}]
    return spec

def compare_wipe(before,after,angle=0,**canvas):
    spec=_base(**canvas);spec['layers']=[{'id':'before','source':_asset(before)},
        {'id':'after','source':_asset(after),'mask':{'type':'linear','rotation':angle,
            'progress':[{'time':0,'value':0},{'time':_last(spec),'value':1}]}}]
    return spec

def screen_overlay(background,overlay,overlay_in=0,overlay_speed=1,**canvas):
    spec=_base(**canvas);spec['layers']=[{'id':'background','source':_asset(background)},
        {'id':'screen','source':_asset(overlay),'source_in':overlay_in,'speed':overlay_speed,'blend':'screen'}]
    return spec

def grid(sources,rows=3,columns=3,hold_at=None,**canvas):
    if isinstance(rows,bool) or isinstance(columns,bool) or not isinstance(rows,int) or not isinstance(columns,int) or not 1<=rows<=6 or not 1<=columns<=6:
        raise ValueError('rows/columns require integers 1..6')
    if rows!=columns:raise ValueError('This contain-grid recipe supports square grids only; custom tiles need explicit crop and mask layers.')
    if not isinstance(sources,list) or len(sources)!=rows*columns:raise ValueError('Exactly rows*columns sources required')
    if hold_at is not None and (not isinstance(hold_at,list) or len(hold_at)!=len(sources)):raise ValueError('hold_at needs one output-time freeze point per source')
    spec=_base(**canvas);duration=spec['canvas']['duration'];fps=spec['canvas']['fps']
    for i,source in enumerate(sources):
        transform={'x':(2*(i%columns)+1)/columns-1,'y':1-(2*(i//columns)+1)/rows,'scale':1/rows}
        if hold_at is None:spec['layers'].append({'id':f'tile{i}','source':_asset(source),**transform})
        else:
            time=hold_at[i]
            if isinstance(time,bool) or not isinstance(time,(int,float)) or not math.isfinite(time) or not 0<=time<=duration-1/fps or abs(time*fps-round(time*fps))>.002:
                raise ValueError('Each hold_at must be frame-aligned and leave at least one frozen frame')
            if time:spec['layers'].append({'id':f'tile{i}play','source':_asset(source),'duration':time,**transform})
            spec['layers'].append({'id':f'tile{i}hold','source':_asset(source),'start':time,'duration':duration-time,'freeze_at':time,**transform})
    return spec

def beat_shake(source,cues,amplitude=.025,burst_seconds=.24,**canvas):
    spec=_base(**canvas);fps=spec['canvas']['fps'];end=_last(spec)
    if not isinstance(cues,list) or any(isinstance(c,bool) or not isinstance(c,(int,float)) or not math.isfinite(c) or not 0<=c<=end for c in cues):raise ValueError('cues need reviewed output seconds within the visible timeline')
    if isinstance(amplitude,bool) or not isinstance(amplitude,(int,float)) or not math.isfinite(amplitude) or not 0<=amplitude<=.1:raise ValueError('amplitude needs 0..0.1 normalized half-canvas units')
    if isinstance(burst_seconds,bool) or not isinstance(burst_seconds,(int,float)) or not math.isfinite(burst_seconds) or not 1/fps<=burst_seconds<=2:raise ValueError('burst_seconds needs one frame..2 seconds')
    # Explicit finite keyframes, not an unvalidated user expression. Per-frame
    # jitter is a designed approximation of shake presets, not tracking.
    points={0:(0,0),round(end*fps):(0,0)};count=max(1,round(burst_seconds*fps))
    for cue in cues:
        onset=round(cue*fps)
        if onset:points[onset-1]=(0,0)
        for n in range(count+1):
            index=onset+n
            if index>round(end*fps):break
            a=amplitude*(1-n/count)
            points[index]=((1 if n%2==0 else -1)*a,(1 if n%4<2 else -1)*a*.6)
    spec['layers']=[{'id':'shake','source':_asset(source),'scale':1+2*amplitude,
        'keyframes':[{'time':index/fps,'x':x,'y':y} for index,(x,y) in sorted(points.items())]}]
    return spec

def danmaku(messages,font_path,font_size_px=48,**canvas):
    spec=_base(**canvas);fps=spec['canvas']['fps'];total=spec['canvas']['duration']
    if not isinstance(messages,list) or not 1<=len(messages)<=64:raise ValueError('messages needs 1..64 entries')
    for i,message in enumerate(messages):
        if not isinstance(message,dict) or set(message)-{'text','start','duration','y','color'}:raise ValueError('message accepts text/start/duration/y/color only')
        start=message.get('start',0)
        if isinstance(start,bool) or not isinstance(start,(int,float)) or not math.isfinite(start):raise ValueError('message start requires finite seconds')
        duration=message.get('duration',total-start)
        if not isinstance(duration,(int,float)) or isinstance(duration,bool) or duration<2/fps:raise ValueError('danmaku duration needs at least two frames')
        spec['layers'].append({'id':f'comment{i}','source':_text(message['text'],font_path,font_size_px,message.get('color','#FFFFFF')),
            'start':start,'duration':duration,'y':message.get('y',0),
            'keyframes':[{'time':0,'x':2},{'time':duration-1/fps,'x':-2}]})
    return spec

def letterbox(source,bar_fraction=.12,text=None,font_path=None,font_size_px=48,**canvas):
    if isinstance(bar_fraction,bool) or not isinstance(bar_fraction,(int,float)) or not math.isfinite(bar_fraction) or not .02<=bar_fraction<=.25:raise ValueError('bar_fraction needs .02..0.25 of canvas height per bar')
    spec=_base(**canvas);spec['layers']=[{'id':'picture','source':_asset(source)}]
    for name,y in [('top',1-bar_fraction),('bottom',bar_fraction-1)]:
        spec['layers'].append({'id':name,'source':{'kind':'solid','color':'#000000'},
            'mask':{'type':'rect','width':1,'height':bar_fraction,'y':y}})
    if text is not None:
        if not font_path:raise ValueError('A real font_path is required for caption text')
        spec['layers'].append({'id':'caption','source':_text(text,font_path,font_size_px),'y':bar_fraction-1})
    return spec

BUILDERS={'freeze':freeze,'glow-title':glow_title,'hollow-title':hollow_title,
          'compare-wipe':compare_wipe,'screen-overlay':screen_overlay,'grid':grid,
          'beat-shake':beat_shake,'danmaku':danmaku,'letterbox':letterbox}

def build(name,parameters):
    if name not in BUILDERS:raise EditError('RECIPE_UNKNOWN','未知技巧配方。',{'available':list(BUILDERS)})
    if not isinstance(parameters,dict):raise ValueError('Recipe parameters must be an object')
    spec=BUILDERS[name](**parameters)
    spec['purpose']=f'Recipe {name}; review subject, timing, resources and readability before using in a story.'
    return spec

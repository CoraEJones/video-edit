"""Source preservation and explicit delivery-quality checks."""
from __future__ import annotations
import math


def selected_rows(plan, rows):
    ids={s['id'] for s in plan.get('shots',[]) if not str(s.get('purpose','')).startswith('panels_')}
    ids.update(s['id'] for s in plan.get('panels',[]))
    ids.update(s.get('id') for s in plan.get('visual_layers',[]) if isinstance(s.get('id'),str))
    return [r for r in rows if r['id'] in ids]


def recommendation(rows, width=16, height=9, plan=None):
    # A change of aspect ratio entails fitting/cropping; it must not also impose
    # the old fixed 1080p ceiling. Photos don't force a video project to 8K.
    videos=[r for r in rows if r.get('kind')!='image']
    source=videos or rows
    edge=max((max(r.get('width',0),r.get('height',0)) for r in source),default=0)
    ratio=width/height
    if ratio>=1:w,h=edge,edge/ratio
    else:w,h=edge*ratio,edge
    rates=[]
    for r in videos:
        rate=float(r.get('fps',0) or 0)
        if plan:
            clips=[s for s in plan.get('shots',[])+plan.get('panels',[])+plan.get('visual_layers',[]) if s.get('id')==r['id'] and not str(s.get('purpose','')).startswith('panels_')]
            rate*=max((min(1,s.get('speed',1)) for s in clips),default=1)
        rates.append(rate)
    rate=max(rates,default=30)
    # Small VFR/NTSC differences are reported, not mistaken for a 30→60 jump.
    fps=next((v for v in (24,25,30,50,60) if v>=rate*.99),60)
    return {'width':max(2,math.ceil(w/2)*2),'height':max(2,math.ceil(h/2)*2),
            'fps':fps,'source_long_edge':edge,'source_playback_fps':rate,
            'hdr_source_ids':[r['id'] for r in videos if r.get('color_transfer') in ('arib-std-b67','smpte2084')]}


def assess(plan, rows):
    rows=selected_rows(plan,rows); rec=recommendation(rows,plan['width'],plan['height'],plan)
    policy=plan.get('request',{}).get('quality_policy','preserve_source')
    reductions=[]
    if max(plan['width'],plan['height'])<rec['source_long_edge']:
        reductions.append('画布分辨率低于所选素材：建议至少 %d × %d。'%(rec['width'],rec['height']))
    if plan['fps']<rec['source_playback_fps']*.99:
        reductions.append('时间线帧率低于所选镜头的播放帧率，请调整计划或说明用户指定的降帧需求。')
    return {'policy':policy,'recommended':rec,'reductions':reductions,
            'native_media':'byte_identical_originals','preview_is_lossless':False}


def preview_settings(plan,cfg):
    from .common import EditError
    mode=cfg.get('preview_mode','full_quality')
    if mode not in ('full_quality','draft'):
        raise EditError('QUALITY_CONFIG','preview_mode 只能是 full_quality 或 draft。')
    w,h=plan['width'],plan['height']
    if mode=='draft':
        limit=cfg.get('preview_width',960)
        if not isinstance(limit,(int,float)) or isinstance(limit,bool) or limit<2:
            raise EditError('QUALITY_CONFIG','快速预览宽度必须至少为 2。')
        w=min(w,int(limit));w=max(2,w//2*2);h=max(2,round(w*plan['height']/plan['width']/2)*2)
    return {'mode':mode,'width':w,'height':h,'crf':16 if mode=='full_quality' else 21,
            'preset':'slow' if mode=='full_quality' else 'veryfast'}

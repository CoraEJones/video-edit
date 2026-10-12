from __future__ import annotations
import math
import re
from pathlib import Path
from .common import EditError, read, probe

SUPPORTED = {'montage','action_opening','slow_fast_slow','shot_size_sequence','split_screen','mask_reveal',
             'j_cut','l_cut','beat_cut','staggered_titles','segmented_speed','zoom','fade',
             'visual_layers','photo_carousel','art_title_overlay'}
ADVANCED = {'optical_flow','motion_tracking','complex_matting','continuous_speed_curve'}

def inventory_for(plan, plan_path):
    if isinstance(plan.get('inventory'),list):return plan['inventory']
    p=Path(plan.get('inventory_path','inventory.json'))
    if not p.is_absolute():p=Path(plan_path).parent/p
    if not p.is_file():raise EditError('INVENTORY_NOT_FOUND','剪辑计划引用的素材清单不存在。',{'path':str(p)})
    data=read(p)
    if isinstance(data,dict) and not isinstance(data.get('media'),list):raise EditError('INVENTORY_FORMAT','素材清单对象必须包含 media 数组。')
    return data['media'] if isinstance(data,dict) else data

def validate(plan, plan_path, cfg, inspect_files=True):
    errors=[];warnings=[]
    def issue(code,where,message):errors.append({'code':code,'at':where,'message':message})
    def number(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)
    if not isinstance(plan,dict):return {'valid':False,'errors':[{'code':'PLAN_FORMAT','message':'计划必须是 JSON 对象'}],'warnings':[]}
    for field in ('review','request','mask_reveal'):
        if field in plan and not isinstance(plan[field],dict):issue('PLAN_FORMAT',field,'需要 JSON 对象')
    for field in ('shots','panels','titles','captions','narration','chapters','visual_layers'):
        if field in plan and (not isinstance(plan[field],list) or any(not isinstance(x,dict) for x in plan[field])):issue('PLAN_FORMAT',field,'需要对象数组')
    if not isinstance(plan.get('techniques',[]),list) or any(not isinstance(x,str) for x in plan.get('techniques',[])):issue('PLAN_FORMAT','techniques','需要技巧名称数组')
    if errors:return {'valid':False,'errors':errors,'warnings':warnings}
    request=plan.get('request',{})
    if request.get('quality_policy','preserve_source') not in ('preserve_source','custom'):
        issue('QUALITY_POLICY','request.quality_policy','需要 preserve_source 或 custom')
    if request.get('quality_policy')=='custom' and (not isinstance(request.get('quality_reason'),str) or not request['quality_reason'].strip()):
        issue('QUALITY_REASON','request.quality_reason','降低交付规格需记录用户要求，不能自行降清晰度')
    if request.get('target_seconds') is not None and (not number(request['target_seconds']) or request['target_seconds']<=0):issue('INVALID_NUMBER','request.target_seconds','需要正数或 null')
    if not isinstance(request.get('must_keep_files',[]),list) or any(not isinstance(x,str) for x in request.get('must_keep_files',[])):issue('PLAN_FORMAT','request.must_keep_files','需要文件路径数组')
    for i,s in enumerate(plan.get('shots',[])+plan.get('panels',[])):
        if not isinstance(s.get('id'),str) or not isinstance(s.get('index'),int) or isinstance(s.get('index'),bool):issue('PLAN_FORMAT',f'clips[{i}]','id 必须是字符串，index 必须是整数')
        for key in ('source_in','duration','speed','start'):
            if not number(s.get(key)):issue('INVALID_NUMBER',f'clips[{i}].{key}','需要有限数值')
    for i,p in enumerate(plan.get('panels',[])):
        if not isinstance(p.get('panel'),int) or isinstance(p.get('panel'),bool) or p['panel'] not in (-1,0,1):issue('PANEL_POSITION',f'panels[{i}]','panel 必须为 -1、0、1')
    for field in ('titles','captions','narration'):
        for i,item in enumerate(plan.get(field,[])):
            if 'language' in item and not isinstance(item['language'],str):issue('PLAN_FORMAT',f'{field}[{i}].language','language 必须为字符串')
            if 'font_family' in item and not isinstance(item['font_family'],str):issue('TEXT_STYLE',f'{field}[{i}].font_family','需要字体名称字符串')
            for key in ('font_id','font_family_en'):
                if key in item and not isinstance(item[key],str):issue('TEXT_STYLE',f'{field}[{i}].{key}','需要字体名称或编号字符串')
            if 'color' in item and (not isinstance(item['color'],str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',item['color'])):issue('TEXT_STYLE',f'{field}[{i}].color','颜色格式为 #RRGGBB')
    if errors:return {'valid':False,'errors':errors,'warnings':warnings}
    for key in ('width','height'):
        if not isinstance(plan.get(key),int):issue('CANVAS_TYPE',key,'画幅尺寸必须是整数')
    for field in ('width','height','fps','duration'):
        if not number(plan.get(field)) or plan[field]<=0:issue('INVALID_NUMBER',field,'需要大于零的有限数值')
    if errors:return {'valid':False,'errors':errors,'warnings':warnings}
    if plan['width']%2 or plan['height']%2:issue('ODD_SIZE','canvas','画面宽高应为偶数')
    from .audio_layers import validate_layers
    validate_layers(plan,cfg,issue,inspect_files)
    if plan['fps'] not in (24,25,30,50,60):issue('FPS_UNSUPPORTED','fps','支持 24/25/30/50/60 fps')
    if plan.get('schema_version','1.0')!='1.0':issue('SCHEMA_UNSUPPORTED','schema_version','不支持的计划版本')
    if 'inventory_path' in plan and not isinstance(plan['inventory_path'],str):return {'valid':False,'errors':[{'code':'INVENTORY_FORMAT','message':'inventory_path 必须是路径字符串'}],'warnings':[]}
    try:rows=inventory_for(plan,plan_path)
    except EditError as e:return {'valid':False,'errors':[{'code':e.code,'message':str(e)}],'warnings':[]}
    if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('id'),str) or not isinstance(r.get('absolute_path'),str) or not number(r.get('duration')) for r in rows):
        return {'valid':False,'errors':[{'code':'INVENTORY_FORMAT','message':'素材清单需要 id、absolute_path、duration'}],'warnings':[]}
    if any('fingerprint' in r and not isinstance(r['fingerprint'],dict) for r in rows):
        return {'valid':False,'errors':[{'code':'INVENTORY_FORMAT','message':'fingerprint 必须是对象'}],'warnings':[]}
    lookup={r['id']:r for r in rows}
    if len(lookup)!=len(rows):issue('DUPLICATE_ASSET','inventory','素材编号必须唯一')
    review=plan.get('review',{})
    if review.get('status')!='reviewed' or not review.get('evidence'):
        issue('REVIEW_REQUIRED','review','需要助手查看联系表/转录并记录剪辑依据，不能直接把分析结果当完成品')
    unsupported=set(plan.get('techniques',[]))-SUPPORTED
    if unsupported:issue('UNSUPPORTED_TECHNIQUE','techniques','尚不能自动执行：'+', '.join(sorted(unsupported)))
    if plan.get('custom_source_crops'):issue('LEGACY_CROP_NEEDS_MIGRATION','custom_source_crops','旧工程专用裁切需要转换，不能静默忽略')
    if plan.get('mask_reveal'):
        m=plan['mask_reveal'];a=m.get('start',0);d=m.get('duration',.7)
        if set(m)-{'start','duration','hold'}:issue('MASK_FIELD','mask_reveal','蒙版仅支持 start、duration、hold')
        if not number(a) or not number(d) or a<0 or d<=0 or a+d>plan['duration']:
            issue('MASK_TIME','mask_reveal','蒙版必须位于有效时间线范围内')
        hold=m.get('hold',d*.25 if number(d) else None)
        if not number(hold) or not number(d) or hold<0 or hold>=d:
            issue('MASK_HOLD','mask_reveal.hold','hold 必须非负且小于揭幕总时长')
    cursor=0;selected=set();indexes=set();shots=plan.get('shots',[])
    if not shots:issue('NO_SHOTS','shots','计划至少需要一个主轨镜头')
    for i,s in enumerate(shots):
        where=f'shots[{i}]'
        if s.get('purpose')=='chapter':issue('LEGACY_CHAPTER_NEEDS_MIGRATION',where,'旧版冻结图卡须转换为明确的照片素材')
        if s.get('index') in indexes:issue('DUPLICATE_SHOT',where,'镜头 index 不能重复')
        indexes.add(s.get('index'))
        for k in ('start','duration','source_in','speed'):
            if not number(s.get(k)):issue('INVALID_NUMBER',where+'.'+k,'需要有限数值')
        if any(not number(s.get(k)) for k in ('start','duration','source_in','speed')):continue
        if abs(s['start']-cursor)>.00002:issue('MAIN_GAP_OR_OVERLAP',where,'主轨必须连续，空白可能被剪映自动吸附')
        if s['duration']<=0 or not .25<=s['speed']<=4 or s['source_in']<0:issue('INVALID_RANGE',where,'时长、速度或素材入点无效')
        if abs(s['duration']*plan['fps']-round(s['duration']*plan['fps']))>.002:issue('OFF_FRAME',where,'镜头时长应对齐项目帧率')
        cursor=s['start']+s['duration']
        for field in ('audio_gain','audio_lead','audio_tail','fade_out'):
            if field in s and (not number(s[field]) or s[field]<0):issue('INVALID_EFFECT',where+'.'+field,'需要非负有限数值')
        if number(s.get('fade_out',0)) and s.get('fade_out',0)>s['duration']:issue('INVALID_EFFECT',where+'.fade_out','淡出不能超过镜头时长')
        if str(s.get('purpose','')).startswith('panels_'):continue
        check_source(s,where,lookup,selected,issue)
        if 'zoom' in s and (not isinstance(s['zoom'],list) or len(s['zoom'])!=2 or not all(number(z) and 1<=z<=2 for z in s['zoom'])):issue('ZOOM_RANGE',where,'zoom 需要两个 1 到 2 的数值')
    if abs(cursor-plan['duration'])>.00002:issue('DURATION_MISMATCH','duration','总时长必须等于主轨末尾')
    groups={}
    for i,p in enumerate(plan.get('panels',[])):
        where=f'panels[{i}]';check_source(p,where,lookup,selected,issue)
        main=next((s for s in shots if s.get('index')==p.get('index')),None)
        if p.get('panel') not in (-1,0,1):issue('PANEL_POSITION',where,'panel 必须为 -1、0、1')
        if not main or not str(main.get('purpose','')).startswith('panels_') or any(p.get(k)!=main.get(k) for k in ('start','duration')):
            issue('PANEL_TIMING',where,'分屏时间必须与黑底主轨镜头一致')
        groups.setdefault(p.get('index'),[]).append(p.get('panel'))
    for s in shots:
        if str(s.get('purpose','')).startswith('panels_') and sorted(groups.get(s['index'],[]))!=[-1,0,1]:issue('PANEL_COUNT','panels','三分屏需要左、中、右三段独立素材')
    from .visual_layers import validate_visual_layers
    validate_visual_layers(plan,lookup,selected,issue)
    from .audio_policy import validate_original_audio
    validate_original_audio(plan,rows,issue)
    for group in ('captions','titles','narration'):
        for i,t in enumerate(plan.get(group,[])):
            for key,low,high in [('x',-1,plan['width']),('y',-1,plan['height']),('size',1,300),('rotation',-360,360)]:
                if key in t and (not number(t[key]) or not low<=t[key]<=high):
                    issue('TEXT_STYLE',f'{group}[{i}].{key}',f'需要 {low} 到 {high} 的有限数值')
            if not number(t.get('start')) or not number(t.get('end')) or not 0<=t['start']<t['end']<=plan['duration']+.00002:
                issue('TEXT_TIME',f'{group}[{i}]','文字/配音时段必须位于时间线内')
            if not any(isinstance(t.get(k),str) and t[k].strip() for k in ('text','zh','en','es')):issue('EMPTY_TEXT',f'{group}[{i}]','文字不能为空')
    request=plan.get('request',{})
    if request.get('voiceover') and not plan.get('narration'):issue('NARRATION_REQUIRED','narration','用户选择了配音，须提供故事文案及时间安排')
    if request.get('voiceover') is False and plan.get('narration'):issue('NARRATION_DISABLED','narration','用户关闭了配音，请移除 narration；故事文案可另存。')
    if request.get('title_mode') == 'fonts_only' and 'art_title_overlay' in plan.get('techniques',[]):issue('ART_TITLE_DISABLED','techniques','用户选择可编辑字体文字，请移除艺术字图片并用 titles 排版。')
    if request.get('subtitles') is False and plan.get('captions'):issue('SUBTITLES_DISABLED','captions','用户关闭了字幕，请移除 captions；片名仍可独立保留')
    wanted={str(Path(p).resolve()).casefold() for p in request.get('must_keep_files',[])}
    actual={str(Path(lookup[i]['absolute_path']).resolve()).casefold() for i in selected if i in lookup}
    if wanted-actual:issue('MUST_KEEP_MISSING','shots','有用户指定必留的素材未进入初稿')
    if request.get('must_keep') and not review.get('must_keep_resolution'):issue('MUST_KEEP_UNRESOLVED','review','请说明必留人物或场景如何匹配到素材；不明确时询问用户')
    for ident in selected:
        r=lookup.get(ident)
        if not r:continue
        p=Path(r['absolute_path'])
        if not p.is_file():issue('MISSING_MEDIA',ident,'素材文件不存在');continue
        fp=r.get('fingerprint',{})
        stat=p.stat()
        if fp and (stat.st_size!=fp.get('size') or stat.st_mtime_ns!=fp.get('mtime_ns')):issue('SOURCE_CHANGED',ident,'素材在分析后改变，请重新分析')
        if inspect_files and r.get('kind')!='image':
            try:
                actual=probe(p,cfg);actual_duration=actual['duration']
                r.update({k:v for k,v in actual.items() if k!='duration'})
                if abs(actual_duration-r['duration'])>.15:issue('SOURCE_DURATION_CHANGED',ident,'探测时长与素材清单不一致')
            except Exception as e:issue('PROBE_FAILED',ident,str(e))
        if r.get('has_audio') and r.get('transcription_status')!='done':warnings.append(f'{ident} 的讲话未识别，重要讲话需另行核实')
    target=request.get('target_seconds')
    if target and abs(plan['duration']-target)>max(5,target*.15):warnings.append('初稿长度偏离理想时长，请在交付说明中解释原因。')
    if errors:return {'valid':False,'errors':errors,'warnings':warnings,'selected_asset_ids':sorted(i for i in selected if isinstance(i,str)),'duration':plan['duration']}
    from .quality import assess
    quality=assess(plan,rows)
    for message in quality['reductions']:
        if quality['policy']=='preserve_source':issue('QUALITY_REDUCTION','canvas/fps',message)
        else:warnings.append(message)
    if quality['recommended']['hdr_source_ids']:warnings.append('HDR 原片不转换；MP4 预览使用 SDR 色调映射，剪映最终 HDR 输出需在导出界面确认。')
    return {'valid':not errors,'errors':errors,'warnings':warnings,'selected_asset_ids':sorted(selected),'duration':plan['duration'],'quality':quality}

def check_source(s,where,lookup,selected,issue):
    ident=s.get('id');selected.add(ident)
    r=lookup.get(ident)
    if not r:issue('UNKNOWN_ASSET',where,'素材编号不在清单里');return
    try:
        a=float(s['source_in']);d=float(s['duration']);v=float(s['speed'])
        if not all(math.isfinite(n) for n in (a,d,v)) or a<0 or d<=0 or v<=0:raise ValueError()
        if r.get('kind')!='image' and a+d*v>float(r['duration'])+.002:issue('SOURCE_OVERFLOW',where,'素材出点超过原片时长')
    except (KeyError,TypeError,ValueError):issue('INVALID_SOURCE_RANGE',where,'素材区间参数无效')

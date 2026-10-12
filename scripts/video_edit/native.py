from __future__ import annotations
import configparser
import time
import uuid
from pathlib import Path
from .common import *
from . import __version__
from .plan import validate, inventory_for
from .sound import prepare_audio
from .assets import prepare_assets
from .text import text_items

def us(t):return round(t*1_000_000)

def rectangle_mask(cfg,required=True,previous=None):
    candidates=[]
    # Preserve the actual resource accepted and saved by this editor. Replacing
    # it with a legacy cache entry can undo a user's working mask on relocation.
    if previous:candidates.append(Path(previous))
    if cfg.get('rectangle_mask_dir'):candidates.append(Path(cfg['rectangle_mask_dir']))
    for effect_id in ('82432980','636077'):
        base=Path(cfg['jianying_user_data'])/'Cache/effect'/effect_id
        if base.is_dir():candidates.extend(sorted((p for p in base.iterdir() if p.is_dir()),key=lambda p:p.stat().st_mtime,reverse=True))
    for p in candidates:
        try:
            if (p/'config.json').is_file() and read(p/'config.json').get('name')=='rect' and (p/'amazingfeature').is_dir():
                return str(p.resolve()).replace('\\','/')
        except (OSError,EditError):continue
    if required:raise EditError('MASK_RESOURCE_MISSING','本机缺少剪映矩形蒙版资源。请在剪映中给任意测试片段选择一次“蒙版→矩形”，保存退出后重试。')
    return None

def codec(cfg):
    import pyJianYingDraft as draft
    if not cfg.get('jianying_install_dir'):
        raise EditError('JIAN YING_NOT_FOUND'.replace(' ',''),'没有找到可用的剪映安装，请在机器配置中指定。')
    return draft.JianyingDraftCryptoCodec(draft.DraftCryptoConfig(jy_install_dir=cfg['jianying_install_dir'],isolated=True,validate_roundtrip=True,backup=False))

def running():
    if os.name!='nt':return False
    p=subprocess.run(['tasklist','/FI','IMAGENAME eq JianyingPro.exe','/NH'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode:raise EditError('PROCESS_STATE_UNAVAILABLE','无法检查剪映是否运行，请在本机桌面环境重试。')
    return b'jianyingpro.exe' in p.stdout.lower()

def auxiliary(folder,ident):
    from PIL import Image
    data=(folder/'draft_content.json').read_bytes()
    (folder/'draft_content.json.bak').write_bytes(data);(folder/'template-2.tmp').write_bytes(data)
    (folder/'draft_biz_config.json').write_bytes(b'')
    write(folder/'draft_agency_config.json',{'is_auto_agency_enabled':False,'is_auto_agency_popup':False,'is_single_agency_mode':False,'marterials':None,'use_converter':False,'video_resolution':720})
    write(folder/'timeline_layout.json',{'dockItems':[{'dockIndex':0,'ratio':1,'timelineIds':[ident],'timelineNames':['时间线01']}],'layoutOrientation':1})
    settings=configparser.ConfigParser();now=int(time.time())
    settings['General']={'draft_create_time':str(now),'draft_last_edit_time':str(now),'real_edit_seconds':'0','real_edit_keys':'0'}
    with (folder/'draft_settings').open('w',encoding='utf8') as f:settings.write(f,space_around_delimiters=False)
    if not (folder/'draft_cover.jpg').is_file():Image.new('RGB',(640,360),'#163044').save(folder/'draft_cover.jpg')

def encode(folder,content,meta,cfg):
    from pyJianYingDraft.draft_codec import write_json_object_with_codec,load_json_object_with_codec
    cc=codec(cfg)
    for name,obj in [('draft_content.json',content),('draft_meta_info.json',meta)]:
        write_json_object_with_codec(folder/name,obj,content_codec=cc,indent=None)
        reread,encrypted=load_json_object_with_codec(folder/name,content_codec=cc)
        if not encrypted or reread!=obj:raise EditError('CODEC_VERIFY_FAILED','剪映工程加密回读不一致。')
    auxiliary(folder,content['id'])

def build_native(plan,assets,sound,folder,cfg):
    import pyJianYingDraft as draft
    from .typography import text_style,caption_line
    font_by_id={}
    def tr(start,duration):return draft.Timerange(us(start),us(duration))
    w,h,fps=plan['width'],plan['height'],plan['fps']
    def original_material(ident):
        asset=assets[ident];material=draft.VideoMaterial(asset['video'])
        # MediaInfo's coded dimensions omit MOV's display rotation. Jianying
        # uses display dimensions for fitting and mask coordinates.
        metadata=asset.get('source_metadata',{})
        material.width=metadata.get('width',material.width)
        material.height=metadata.get('height',material.height)
        return material
    with tempfile.TemporaryDirectory(prefix='video-edit-native-') as temp:
        root=Path(temp)/'drafts';root.mkdir()
        df=draft.DraftFolder(str(root),user_data_path=str(Path(temp)/'User Data'))
        p=df.create_draft(plan['name'],w,h,fps=fps,allow_replace=False)
        vt=p.append_tracks([draft.TrackSpec(draft.TrackType.video,'故事主线 · 可回拉的独立镜头')])[0]
        panel_tracks=p.append_tracks([draft.TrackSpec(draft.TrackType.video,f'蒙版三分屏 · {s}') for s in ('左','中','右')]) if plan.get('panels') else []
        for s in plan['shots']:
            black=str(s.get('purpose','')).startswith('panels_')
            path=str(folder/'assets/graphics/black.png') if black else original_material(s['id'])
            src=None if black or assets.get(s['id'],{}).get('kind')=='image' else tr(s['source_in'],s['duration']*s['speed'])
            seg=draft.VideoSegment(path,tr(s['start'],s['duration']),source_timerange=src,volume=0)
            if s.get('zoom'):
                for t,z in [(0,s['zoom'][0]),(max(0,s['duration']-1/fps),s['zoom'][1])]:seg.add_keyframe(draft.KeyframeProperty.uniform_scale,us(t),z)
            if s.get('fade_out'):
                seg.add_keyframe(draft.KeyframeProperty.alpha,us(max(0,s['duration']-s['fade_out'])),1)
                seg.add_keyframe(draft.KeyframeProperty.alpha,us(s['duration']),0)
            p.add_segment(seg,track=vt)
        for s in plan.get('panels',[]):
            material=original_material(s['id'])
            src=None if assets[s['id']]['kind']=='image' else tr(s['source_in'],s['duration']*s['speed'])
            seg=draft.VideoSegment(material,tr(s['start'],s['duration']),source_timerange=src,volume=0,
                clip_settings=draft.ClipSettings(transform_x=s['panel']*.66))
            fit=min(w/material.width,h/material.height)
            # Mask fractions refer to the fitted original, no longer to a
            # full-canvas re-encoded image with baked-in letterboxing.
            seg.add_mask(draft.MaskType.矩形,size=min(1,.86*h/(material.height*fit)),
                         rect_width=min(1,.30*w/(material.width*fit)))
            p.add_segment(seg,track=panel_tracks[s['panel']+1])
        from .visual_layers import normalized_layers,initial_position
        for i,s in enumerate(normalized_layers(plan)):
            material=original_material(s['id']);position=initial_position(s)
            src=None if assets[s['id']]['kind']=='image' else tr(s['source_in'],s['duration']*s['speed'])
            seg=draft.VideoSegment(material,tr(s['start'],s['duration']),source_timerange=src,volume=0,
                clip_settings=draft.ClipSettings(transform_x=position['x'],transform_y=position['y'],
                                                scale_x=s['scale'],scale_y=s['scale']))
            for key in s.get('keyframes',[]):
                seg.add_keyframe(draft.KeyframeProperty.position_x,us(key['time']),key['x'])
                seg.add_keyframe(draft.KeyframeProperty.position_y,us(key['time']),key['y'])
            track=p.append_tracks([draft.TrackSpec(draft.TrackType.video,f'视觉叠层 {i+1} · '+s.get('purpose',s['id']))])[0]
            p.add_segment(seg,track=track)
        if plan.get('mask_reveal'):
            m=plan['mask_reveal'];a=m.get('start',0);d=m.get('duration',.7)
            for sign in (1,-1):
                track=p.append_tracks([draft.TrackSpec(draft.TrackType.video,'开场矩形蒙版 '+str(sign))])[0]
                seg=draft.VideoSegment(str(folder/'assets/graphics/black.png'),tr(a,d),clip_settings=draft.ClipSettings(transform_y=sign*.5))
                seg.add_mask(draft.MaskType.矩形,size=.5,rect_width=1)
                hold=m.get('hold',d*.25)
                for t,y in [(0,sign*.5)]+([(hold,sign*.5)] if hold>0 else [])+[(d,sign*1.5)]:seg.add_keyframe(draft.KeyframeProperty.position_y,us(t),y)
                p.add_segment(seg,track=track)
        lanes={}
        def lane(group,start,end,typ,label):
            pool=lanes.setdefault(group,[])
            item=next((x for x in pool if x['end']<=start+.000001),None)
            if item is None:
                item={'end':0,'handle':p.append_tracks([draft.TrackSpec(typ,label+f' {len(pool)+1}')])[0]};pool.append(item)
            item['end']=end;return item['handle']
        for e in sorted(sound['events'],key=lambda e:e['start']):
            label={'music':'配乐 · 讲话时压低','ambience':'环境增强 · 库音','sfx':'动作音效 · 库音','voiceover':'故事配音','original':'现场原声 · J/L 衔接'}.get(e['track'],e['track'])
            track=lane(e['track'],e['start'],e['start']+e['duration'],draft.TrackType.audio,label)
            seg=draft.AudioSegment(e['path'],tr(e['start'],e['duration']),source_timerange=tr(e['source_in'],e['duration']),volume=e['gain'])
            for t,g in e['keys']:seg.add_keyframe(us(t),g*e['gain'])
            seg.add_fade(us(e['fade_in']),us(e['fade_out']));p.add_segment(seg,track=track)
        for kind in ('captions','titles'):
            for item in sorted(plan.get(kind,[]),key=lambda x:x['start']):
                for line,(lang,text) in enumerate(text_items(item)):
                    caption=kind=='captions'
                    if caption:line=caption_line(plan,item,lang)
                    style=text_style(item,caption,line,lang);y=style['y']
                    x=item.get('x',0) if not caption else 0
                    # New plans use normalized coordinates. Accept legacy v5 pixel coordinates.
                    if abs(x)>2:x=(x-w/2)/(w/2)
                    if abs(y)>2:y=(h/2-y)/(h/2)
                    size=style['size']
                    if size>30:size/=7
                    seg=draft.TextSegment(text,tr(item['start'],item['end']-item['start']),
                        style=draft.TextStyle(size=size,bold=style['bold'],color=tuple(style['color']),align=1,auto_wrapping=True,max_line_width=.86),
                        border=draft.TextBorder(color=tuple(style['outline']),width=style['border_width']),
                        clip_settings=draft.ClipSettings(transform_x=x,transform_y=y,rotation=item.get('rotation',0)))
                    if not caption and item.get('animate',True):
                        seg.add_keyframe(draft.KeyframeProperty.position_y,0,y-.035)
                        seg.add_keyframe(draft.KeyframeProperty.position_y,us(min(.24,(item['end']-item['start'])/3)),y)
                    track=lane(kind+lang,item['start'],item['end'],draft.TrackType.text,('字幕 · ' if caption else '错落标题 · ')+lang)
                    p.add_segment(seg,track=track)
                    font_by_id[seg.material_id]=style['font']
        p.save()
        for f in (root/plan['name']).iterdir():
            if f.is_file():shutil.copy2(f,folder/f.name)
    content=read(folder/'draft_content.json');meta=read(folder/'draft_meta_info.json')
    # Jianying 11.5 discards the library's legacy `masks` pool on load.
    # Native drafts and the library template use `common_mask` instead.
    masks=content['materials'].pop('masks',[])
    for mask in masks:mask['path']=rectangle_mask(cfg)
    if masks:content['materials'].setdefault('common_mask',[]).extend(masks)
    font=str(Path(cfg['font_path']).resolve()).replace('\\','/')
    if not Path(font).is_file():raise EditError('FONT_MISSING','没有找到字幕字体，请配置本机中文字体。')
    for mat in content['materials'].get('texts',[]):
        selected=font_by_id.get(mat['id']) or {'path':font,'family':'Microsoft YaHei'}
        actual_font=str(Path(selected['path']).resolve()).replace('\\','/')
        rich=json.loads(mat['content'])
        for style in rich['styles']:style['font']={'id':'','path':actual_font}
        mat['content']=json.dumps(rich,ensure_ascii=False);mat.update(font_name=selected['family'],font_title=selected['family'],font_path=actual_font)
    meta['draft_fold_path']=str(folder);meta['draft_root_path']=str(folder.parent)
    encode(folder,content,meta,cfg)
    return content,meta

def register(folder,content,meta,cfg):
    from pyJianYingDraft.draft_registration import DraftFolderRegistration
    if running():raise EditError('CLOSE_JIANYING','工程已生成。请保存当前工作并退出剪映，再登记新工程。',{'draft_path':str(folder)})
    reg=DraftFolderRegistration(str(folder.parent),user_data_path=cfg['jianying_user_data'],content_codec=codec(cfg))
    index=Path(reg.root_meta_info_path());payload=reg.read_root_meta_payload();before=payload.get('all_draft_store',[]).copy()
    for old in before:
        if old.get('draft_id')==content['id'] and Path(old.get('draft_fold_path','')).resolve()==folder:
            return {'registered':True,'already_registered':True,'index':str(index)}
        if old.get('draft_id')==content['id'] or old.get('draft_name')==meta['draft_name']:
            raise EditError('DRAFT_ALREADY_EXISTS','首页已有同名或同 ID 工程，请给副本换一个名字。')
    backup=folder/'registration-backups'/f'root_meta_info_{time.time_ns()}.json';backup.parent.mkdir(exist_ok=True)
    if index.is_file():shutil.copy2(index,backup)
    now=int(time.time()*1e6)
    entry=reg.build_root_meta_entry(existing_entry=None,draft_name=meta['draft_name'],draft_path=str(folder),draft_id=content['id'],
        draft_new_version=str(content.get('new_version',meta.get('draft_new_version',''))),tm_draft_create=now,tm_draft_modified=now,
        tm_duration=content['duration'],timeline_materials_size=sum(p.stat().st_size for p in (folder/'assets').rglob('*') if p.is_file()))
    payload.setdefault('all_draft_store',[]).append(entry)
    # Compare immediately before write to avoid replacing a concurrently changed homepage.
    if reg.read_root_meta_payload().get('all_draft_store',[])!=before:
        raise EditError('HOME_CHANGED','剪映首页信息刚刚发生变化，未写入，请重试。')
    reg.write_root_meta_info(payload)
    after=reg.read_root_meta_payload()['all_draft_store']
    if after[:-1]!=before or after[-1]['draft_id']!=content['id']:raise EditError('REGISTRATION_VERIFY_FAILED','首页登记后校验未通过。')
    return {'registered':True,'index':str(index),'backup':str(backup),'existing_drafts_preserved':True}

def package_manifest(folder,content,cfg):
    mappings={}
    for kind in ('videos','audios'):
        for m in content['materials'].get(kind,[]):
            if m.get('path'):
                p=Path(m['path']).resolve()
                try:relative=p.relative_to(folder)
                except ValueError:raise EditError('EXTERNAL_MEDIA','工程包含未打包的媒体。',{'path':str(p)})
                mappings[m['path']]=str(relative).replace('\\','/')
    for p in (folder/'assets/fonts').glob('*'):
        if p.is_file() and p.suffix.lower() in ('.ttf','.otf','.ttc'):
            mappings[str(p.resolve())]=p.relative_to(folder).as_posix()
            mappings[str(p.resolve()).replace('\\','/')]=p.relative_to(folder).as_posix()
    write(folder/'portable-manifest.json',{'schema_version':'1.0','original_root':str(folder),'media_paths':mappings,
        'font_path':cfg['font_path'],'tool_version':__version__,'note':'移动后使用修复与登记入口，避免旧绝对路径。'})

def package_editorial(plan,rows,assets,folder,plan_path):
    """Keep the plan and its review evidence usable after moving the package."""
    import copy
    local=copy.deepcopy(plan);local.pop('inventory',None);local['inventory_path']='inventory.json'
    local_rows=[];mapping={}
    for row in rows:
        if row['id'] not in assets:continue
        r=copy.deepcopy(row);dest=Path(assets[r['id']]['original'])
        mapping[str(Path(r['absolute_path']).resolve()).casefold()]=str(dest)
        r['source_provenance']=r['absolute_path'];r['absolute_path']=str(dest)
        r['relative_path']=str(dest.relative_to(folder));stat=dest.stat()
        r['fingerprint']={'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}
        evidence=folder/'evidence'/r['id'];evidence.mkdir(parents=True,exist_ok=True)
        def copy_evidence(p):
            src=Path(p)
            if not src.is_file():return None
            target=evidence/src.name
            if src.resolve()!=target.resolve():shutil.copy2(src,target)
            return str(target)
        r['frames']=[dict(f,path=target) for f in r.get('frames',[]) if (target:=copy_evidence(f['path']))]
        r['contact_sheets']=[target for p in r.get('contact_sheets',[]) if (target:=copy_evidence(p))]
        local_rows.append(r)
    req=local.setdefault('request',{})
    req['media_dir']=str(folder/'assets/originals')
    req['must_keep_files']=[mapping[str(Path(p).resolve()).casefold()] for p in req.get('must_keep_files',[]) if str(Path(p).resolve()).casefold() in mapping]
    for i,layer in enumerate(local.get('audio_layers',[])):
        bundled=folder/'assets/audio'/f'库音原件_{i:03d}{Path(layer["path"]).suffix}'
        if not bundled.is_file():raise EditError('AUDIO_COPY','附加音轨原件尚未打包')
        layer['path']=str(bundled)
    if req.get('music_file') and not any(x.get('kind')=='music' for x in local.get('audio_layers',[])) and req.get('music')!='只保留原声':
        bundled=folder/'assets/music'/('原音乐'+Path(req['music_file']).suffix)
        if not bundled.is_file():raise EditError('AUDIO_COPY','自选音乐原件尚未打包')
        req['music_file']=str(bundled)
    write(folder/'edit-plan.json',local);write(folder/'inventory.json',local_rows)
    story=Path(plan_path).parent/'story.txt'
    if story.is_file():shutil.copy2(story,folder/'story.txt')

def export(plan_path,out,cfg,name=None,do_register=False,preview=True):
    plan_path=resolve_path(plan_path)
    plan=read(plan_path)
    from .intake import require_delivery_request
    require_delivery_request(plan.get('request',{}),out,'editable',cfg)
    plan['name']=safe_name(name or plan.get('name','我的回忆'))
    report=validate(plan,plan_path,cfg)
    if not report['valid']:raise EditError('INVALID_PLAN','剪辑计划检查未通过。',report)
    codec(cfg) # fail before copying large original media
    if plan.get('panels') or plan.get('mask_reveal'):rectangle_mask(cfg)
    folder=resolve_path(out)/plan['name']
    if folder.exists():raise EditError('OUTPUT_EXISTS','输出工程已经存在，请使用新的作品名称或输出位置。',{'path':str(folder)})
    folder.mkdir(parents=True)
    rows=inventory_for(plan,plan_path)
    write(folder/'edit-plan.json',plan);write(folder/'inventory.json',rows)
    write(folder/'validation.json',report)
    try:
        assets=prepare_assets(plan,rows,folder,cfg);write(folder/'prepared-assets.json',assets)
        from .typography import prepare
        prepare(plan,assets,folder,cfg)
        progress('准备独立音轨与配乐…');sound=prepare_audio(plan,assets,folder,cfg)
        package_editorial(plan,rows,assets,folder,plan_path)
        progress('生成剪映可编辑轨道…');content,meta=build_native(plan,assets,sound,folder,cfg)
        package_manifest(folder,content,cfg)
        from .preview import render_preview,write_srt
        srt=write_srt(plan,folder)
        movie=render_preview(plan,assets,folder,cfg) if preview else None
        audit={'tool_version':__version__,'draft_path':str(folder),'duration_seconds':content['duration']/1e6,
            'draft_id':content['id'],'encrypted_roundtrip':True,'registered':False,'ui_verified':False,
            'tracks':[{'type':t['type'],'name':t.get('name'),'segments':len(t['segments'])} for t in content['tracks']],
            'mask_count':len(content['materials'].get('common_mask',[])),'originals_copied_in_full':True,
            'preview':str(movie) if movie else None,'srt':srt,'warnings':report['warnings']+sound.get('warnings',[]),'voices':sound.get('voices',[]),
            'quality':report['quality'],'native_uses_originals':True,'video_reencoding_before_edit':False,
            'preview_quality':read(folder/'preview-quality.json') if movie else None,
            'normalization':'剪映直接引用完整原片副本，无视频转码、缩小或 HDR 转 SDR。'}
        write(folder/'verification.json',audit)
        quality_text=(f'本工程：{plan["width"]} × {plan["height"]}，{plan["fps"]} 帧/秒。\n'
            '剪映时间线直接使用完整原片副本，没有预先压缩视频。\n'
            '在剪映点击“导出”：选择上述分辨率和帧率，码率选择高质量；不要选择低码率或压缩小文件。\n'
            '混合画幅、裁切、放大和分屏会改变构图，合成 MP4 仍需编码；高画质不等于数学无损。\n'
            'MP4 预览用于审片。若有 HDR 原片，预览会转为 SDR，工程中的原片仍保留 HDR；最终 HDR 成片需确认剪映导出设置。\n')
        (folder/'画质与导出说明.txt').write_text(quality_text,encoding='utf-8-sig')
        (folder/'打开工程说明.txt').write_text('在另一台电脑或移动目录后，请让 video-edit 助手修复并登记本文件夹。\n也可以双击“修复并打开工程.cmd”，选择已安装的 video-edit 文件夹。\n打开后可独立修改字幕、配乐、原声和镜头。完整原始素材在 assets/originals。\n',encoding='utf8')
        shutil.copy2(ROOT/'scripts/open-package.ps1',folder/'open-package.ps1')
        (folder/'修复并打开工程.cmd').write_text('@echo off\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-package.ps1"\r\n',encoding='ascii')
        if do_register:
            audit.update(register(folder,content,meta,cfg));write(folder/'verification.json',audit)
        return audit
    except Exception as exc:
        write(folder/'failure.json',{'message':str(exc),'code':getattr(exc,'code','EXPORT_FAILED'),'partial_output':str(folder)})
        raise

def relocate(folder,cfg,name=None,do_register=False):
    from pyJianYingDraft.draft_codec import load_json_object_with_codec,write_json_object_with_codec
    folder=Path(folder).resolve()
    if running():raise EditError('CLOSE_JIANYING','请保存工作并退出剪映，再修复工程路径。')
    manifest=read(folder/'portable-manifest.json');cc=codec(cfg)
    content,_=load_json_object_with_codec(folder/'draft_content.json',content_codec=cc)
    meta,_=load_json_object_with_codec(folder/'draft_meta_info.json',content_codec=cc)
    backup=folder/'relocation-backups'/str(time.time_ns());backup.mkdir(parents=True)
    for n in ('draft_content.json','draft_meta_info.json','portable-manifest.json'):shutil.copy2(folder/n,backup/n)
    oldroot=Path(manifest['original_root']);paths=manifest['media_paths']
    oldid=content['id'];newid=str(uuid.uuid4()).upper() if name else oldid
    def replacement(value):
        if not isinstance(value,str):return value
        if name and value==oldid:return newid
        if value in paths:
            p=(folder/paths[value]).resolve()
            if not p.is_relative_to(folder) or not p.is_file():raise EditError('PACKAGE_MEDIA_MISSING','工程包内的素材不存在或路径无效。',{'path':str(p)})
            return str(p)
        try:
            relative=Path(value).relative_to(oldroot)
            if name:relative=Path(*(newid if part==oldid else part for part in relative.parts))
            return str(folder/relative)
        except (ValueError,OSError):return value
    def walk(obj):
        if isinstance(obj,dict):return {k:walk(v) for k,v in obj.items()}
        if isinstance(obj,list):return [walk(v) for v in obj]
        return replacement(obj)
    from .typography import fonts
    catalog=fonts(cfg);font_fallbacks=[]
    def rebind_font(previous):
        previous=replacement(previous)
        found=catalog.get(Path(previous).name.casefold())
        font_path=str(Path(previous).resolve()) if previous and Path(previous).is_file() else found['path'] if found else cfg['font_path']
        if not found and font_path!=previous:font_fallbacks.append({'from':previous,'to':font_path})
        return font_path.replace('\\','/'),found
    def repair_content(document):
        document=walk(document)
        for mask in document.get('materials',{}).get('common_mask',[]):
            if mask.get('resource_type')=='rectangle':mask['path']=rectangle_mask(cfg,previous=mask.get('path'))
        for m in document.get('materials',{}).get('texts',[]):
            previous=m.get('font_path','');font_path,found=rebind_font(previous)
            rich=json.loads(m['content'])
            for style in rich.get('styles',[]):
                oldfont=style.get('font',{});style_path,_=rebind_font(oldfont.get('path') or previous)
                style['font']=dict(oldfont,path=style_path)
            m['content']=json.dumps(rich,ensure_ascii=False);m['font_path']=font_path
            if found:m['font_name']=m['font_title']=found['family']
        for kind in ('videos','audios'):
            for m in document.get('materials',{}).get(kind,[]):
                if m.get('path') and not Path(m['path']).resolve().is_relative_to(folder):raise EditError('EXTERNAL_MEDIA','编辑器加入了包外媒体，请先打包它们。')
                if m.get('path') and not Path(m['path']).is_file():raise EditError('PACKAGE_MEDIA_MISSING','工程包缺少媒体文件。',{'path':m['path']})
        return document
    content=repair_content(content);meta=walk(meta)
    if name:meta['draft_name']=safe_name(name)
    meta['draft_fold_path']=str(folder);meta['draft_root_path']=str(folder.parent)
    # Jianying creates a second, editable copy under Timelines after the first
    # save. Repair every current timeline, never reconstruct from the old plan.
    docs={folder/'draft_content.json':content,folder/'draft_meta_info.json':meta}
    for path in (folder/'Timelines').rglob('draft_content.json'):
        obj,_=load_json_object_with_codec(path,content_codec=cc);docs[path]=repair_content(obj)
    for path,obj in docs.items():
        target=backup/path.relative_to(folder);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    for path,obj in docs.items():
        write_json_object_with_codec(path,obj,content_codec=cc,indent=None)
        if load_json_object_with_codec(path,content_codec=cc)[0]!=obj:raise EditError('CODEC_VERIFY_FAILED','搬迁后回读不一致。')
        shutil.copy2(path,path.with_name(path.name+'.bak'))
    for path in (folder/'Timelines/project.json',folder/'timeline_layout.json'):
        if path.is_file():
            target=backup/path.relative_to(folder);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            write(path,walk(read(path)))
    if name and oldid!=newid:
        olddir=(folder/'Timelines'/oldid).resolve();newdir=(folder/'Timelines'/newid).resolve()
        if olddir.is_dir():
            if not olddir.is_relative_to(folder) or not newdir.is_relative_to(folder) or newdir.exists():raise EditError('TIMELINE_RENAME_CONFLICT','新时间线目录发生冲突。')
            olddir.rename(newdir)
    shutil.copy2(folder/'draft_content.json',folder/'template-2.tmp')
    package_manifest(folder,content,cfg)
    for file in ('edit-plan.json','inventory.json','prepared-assets.json','audio-plan.json','verification.json'):
        path=folder/file
        if path.is_file():
            shutil.copy2(path,backup/file);updated=walk(read(path))
            if file=='edit-plan.json' and name:updated['name']=name
            if file=='verification.json' and folder!=oldroot:
                updated['ui_verified_before_move']=updated.get('ui_verified',False);updated['ui_verified']=False
            write(path,updated)
    audit={'relocated':True,'draft_path':str(folder),'draft_id':content['id'],'editor_changes_preserved':True,'timelines_repaired':len(docs)-2,'font_fallbacks':font_fallbacks,'backup':str(backup),'relocation_backup':str(backup),'registered':False}
    if do_register:audit.update(register(folder,content,meta,cfg))
    verification=folder/'verification.json'
    if verification.is_file():
        updated=read(verification);updated.update(draft_path=str(folder),draft_id=content['id'],registered=audit['registered'])
        write(verification,updated)
    write(folder/'relocation-verification.json',audit)
    return audit

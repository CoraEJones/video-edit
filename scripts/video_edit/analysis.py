from __future__ import annotations
import hashlib
import math
from pathlib import Path
from .common import *

def analyze(media, out, request, cfg, transcribe=True, reuse=True):
    from .intake import require_confirmed_request
    require_confirmed_request(request,cfg)
    if resolve_path(media)!=resolve_path(request['media_dir']):
        raise EditError('REQUEST_MEDIA_MISMATCH','分析目录与用户确认的素材目录不同，请重新确认。')
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    media,out = resolve_path(media),resolve_path(out)
    if not media.is_dir():
        raise EditError('MEDIA_NOT_FOUND','所选素材文件夹不存在。')
    if out == media:
        raise EditError('OUTPUT_EQUALS_INPUT','输出目录不能就是原始素材目录。')
    out.mkdir(parents=True, exist_ok=True)
    existing = read(out/'inventory.json') if reuse and (out/'inventory.json').is_file() else []
    old = {r['absolute_path']:r for r in existing}
    files = sorted(p for p in media.rglob('*') if p.is_file() and p.suffix.lower() in VIDEO_EXTS|IMAGE_EXTS and out not in p.parents)
    if not files:
        raise EditError('NO_MEDIA','这个文件夹里没有找到支持的视频或照片。')
    rows, warnings = [], []
    font = ImageFont.truetype(cfg['font_path'],17) if Path(cfg['font_path']).is_file() else ImageFont.load_default()
    whisper = None
    required_transcription = bool(cfg.get('transcription_required', False))
    if required_transcription and not transcribe:
        raise EditError('TRANSCRIPTION_REQUIRED','此次需求要求识别讲话，不能同时使用 --no-transcribe；请调整需求或配置后再继续。')
    model = model_path(cfg)
    if transcribe and not model:
        if required_transcription:
            raise EditError('TRANSCRIPTION_UNAVAILABLE','此次需要语音识别，但本地模型未配置；请先按需配置识别组件和模型。')
        warnings.append('本地语音模型未配置：讲话尚未识别，不能声称已保留所有重要讲话。')
    for number,p in enumerate(files,1):
        progress(f'分析素材 {number}/{len(files)}：{p.name}')
        stat = p.stat()
        ident = 'v'+hashlib.sha256(str(p).casefold().encode()).hexdigest()[:12]
        fingerprint = {'size':stat.st_size,'mtime_ns':stat.st_mtime_ns}
        cached = old.get(str(p))
        if cached and cached.get('fingerprint') == fingerprint and all(Path(x['path']).is_file() for x in cached.get('frames',[])) and (not transcribe or cached.get('transcription_status')=='done'):
            rows.append(cached); continue
        r = {'id':ident,'filename':p.name,'absolute_path':str(p),'relative_path':str(p.relative_to(media)),
             'fingerprint':fingerprint,'kind':'image' if p.suffix.lower() in IMAGE_EXTS else 'video',
             'frames':[],'transcript':[],'transcription_status':'not_requested','semantic_review':None}
        try:
            if r['kind']=='image':
                with Image.open(p) as im:
                    from PIL import ImageOps
                    im = ImageOps.exif_transpose(im)
                    r.update(width=im.width,height=im.height,duration=5,fps=0,has_audio=False)
                times = [0]
            else:
                r.update(probe(p,cfg))
                if r['duration'] <= 0:
                    raise ValueError('无法读出素材时长')
                count = min(int(cfg['max_samples_per_video']),max(3,math.ceil(r['duration']/float(cfg['sample_interval_seconds']))))
                times = [round(r['duration']*(i+.5)/count,3) for i in range(count)]
            frames_dir = out/'frames'/ident
            frames_dir.mkdir(parents=True,exist_ok=True)
            tiles=[]
            for i,t in enumerate(times):
                dest = frames_dir/f'{i:03d}_{t:.3f}.jpg'
                if r['kind']=='image':
                    with Image.open(p) as source:
                        im=ImageOps.exif_transpose(source).convert('RGB');im.thumbnail((640,640));im.save(dest)
                else:
                    run([cfg['ffmpeg'],'-v','error','-ss',t,'-i',p,'-frames:v','1','-vf','scale=640:640:force_original_aspect_ratio=decrease','-y',dest],timeout=120)
                with Image.open(dest) as frame:
                    a=np.asarray(frame.convert('L').resize((160,90)),dtype=float)
                    sharp=float(np.var(np.diff(a,axis=0))+np.var(np.diff(a,axis=1)))
                    r['frames'].append({'path':str(dest),'time':t,'brightness':round(float(a.mean()),2),'sharpness':round(sharp,2)})
                    tile=Image.new('RGB',(330,224),'#182333'); pic=frame.convert('RGB');pic.thumbnail((324,184));tile.paste(pic,((330-pic.width)//2,4+(184-pic.height)//2))
                    ImageDraw.Draw(tile).text((8,194),f'{ident}  {t:.2f}s',font=font,fill='white');tiles.append(tile)
            for page in range(0,len(tiles),12):
                subset=tiles[page:page+12];sheet=Image.new('RGB',(990,224*math.ceil(len(subset)/3)),'#182333')
                for i,tile in enumerate(subset):sheet.paste(tile,((i%3)*330,(i//3)*224))
                dest=frames_dir/f'contact_{page//12+1}.jpg';sheet.save(dest,quality=86)
                r.setdefault('contact_sheets',[]).append(str(dest))
            if r['has_audio'] and transcribe and model:
                # Optional ASR is independent of visual analysis. A missing or
                # broken speech component must not discard valid sampled frames.
                try:
                    if whisper is None:
                        from faster_whisper import WhisperModel
                        whisper=WhisperModel(model,device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
                    wav=out/'audio'/f'{ident}.wav';wav.parent.mkdir(exist_ok=True)
                    run([cfg['ffmpeg'],'-v','error','-i',p,'-vn','-ac','1','-ar','16000','-y',wav])
                    segments,info=whisper.transcribe(str(wav),language=cfg.get('input_language'),word_timestamps=True,vad_filter=True)
                    r['transcript']=[{'start':s.start,'end':s.end,'text':s.text.strip(),
                        'avg_logprob':s.avg_logprob,'no_speech_prob':s.no_speech_prob,'compression_ratio':s.compression_ratio,
                        'confidence_warning':s.avg_logprob < -1 or s.no_speech_prob > .6 or s.compression_ratio > 2.4,
                        'words':[{'start':w.start,'end':w.end,'word':w.word} for w in s.words or []]} for s in segments]
                    r['speech_language']=info.language;r['language_probability']=info.language_probability
                    r['transcription_status']='done';r['transcript_review']='需要试听核实；done 仅表示识别程序完成，不表示讲话内容正确'
                except Exception as exc:
                    if required_transcription:
                        raise EditError('TRANSCRIPTION_FAILED','此次要求的讲话识别未完成，不能继续声称转录成功；请修复组件或明确调整需求。',
                                        {'path':str(p),'reason':f'{type(exc).__name__}: {exc}'}) from exc
                    r['transcript']=[];r['transcription_status']='failed';r['transcription_error']=f'{type(exc).__name__}: {exc}'
                    warnings.append(f'{p.name}：可选语音识别未完成，画面分析保留；{exc}')
            elif not r['has_audio']:
                r['transcription_status']='no_audio'
            else:
                r['transcription_status']='unavailable' if transcribe else 'not_requested'
            r['status']='analyzed'
        except Exception as exc:
            if isinstance(exc,EditError) and exc.code=='TRANSCRIPTION_FAILED':raise
            r['status']='analysis_failed';r['error']=str(exc)
            warnings.append(f'{p.name}：{exc}')
        rows.append(r)
        write(out/'inventory.json',rows)
    write(out/'request.json',request)
    from .quality import recommendation
    aspect=request.get('aspect','横屏 16:9')
    aw,ah=(9,16) if '9:16' in aspect else (1,1) if '1:1' in aspect else (16,9)
    quality=recommendation([r for r in rows if r.get('status')=='analyzed'],aw,ah)
    write(out/'analysis-report.json',{'warnings':warnings,'media_count':len(rows),'semantic_review_required':True,
                                    'recommended_quality':quality,
                                    'sampling_limit':'抽样画面和清晰度仅为证据，不能自动证明人物身份、重要事件或整段画面质量。'})
    return {'inventory':str(out/'inventory.json'),'request':str(out/'request.json'),'report':str(out/'analysis-report.json'),
            'media_count':len(rows),'ready_count':sum(r.get('status')=='analyzed' for r in rows),
            'recommended_quality':quality,
            'contact_sheets':[p for r in rows for p in r.get('contact_sheets',[])],
            'next_action':'按 material-analysis.md 实际审看帧与转录，候选段用 review_frames.py 补帧；形成 material-analysis.json 与故事线，再依 plan-format.md 精剪、验证和导出。','warnings':warnings}

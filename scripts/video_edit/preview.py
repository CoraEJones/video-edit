from __future__ import annotations
from pathlib import Path
from .common import *
from .text import text_items
from .color import input_color_filter

def timecode(t,ass=False):
    if ass:
        n=round(t*100);h,n=divmod(n,360000);m,n=divmod(n,6000);s,cs=divmod(n,100)
        return f'{h}:{m:02}:{s:02}.{cs:02}'
    n=round(t*1000);h,n=divmod(n,3600000);m,n=divmod(n,60000);s,ms=divmod(n,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'

def write_srt(plan,folder):
    groups={}
    for c in sorted(plan.get('captions',[]),key=lambda c:c['start']):
        for lang,text in text_items(c):groups.setdefault(lang,[]).append((c,text))
    results=[]
    for lang,rows in groups.items():
        name='字幕_'+safe_name(lang)+'.srt';p=folder/name
        p.write_text('\n'.join(f'{i}\n{timecode(c["start"])} --> {timecode(c["end"])}\n{text}\n' for i,(c,text) in enumerate(rows,1)),encoding='utf-8-sig');results.append(str(p))
    return results

def render_preview(plan,assets,folder,cfg):
    work=folder/'preview-work';work.mkdir(exist_ok=True)
    from .quality import preview_settings
    quality=preview_settings(plan,cfg);w,h=quality['width'],quality['height']
    write_ass(plan,folder,w,h)
    fps=plan['fps'];clips=[]
    for s in plan['shots']:
        progress(f'生成预览镜头 {s["index"]}…')
        dest=work/f'{s["index"]:04d}.mkv';cmd=[cfg['ffmpeg'],'-v','error']
        panel=[p for p in plan.get('panels',[]) if p['index']==s['index']]
        items=panel or [s];filters=[]
        for item in items:
            a=assets[item['id']]
            if a['kind']=='image':cmd+=['-loop','1','-framerate',fps,'-i',a['video']]
            else:cmd+=['-ss',item['source_in'],'-i',a['video']]
        for i,item in enumerate(items):
            a=assets[item['id']]
            filters.append(f'[{i}:v]setpts=(PTS-STARTPTS)/{item["speed"]},fps={fps},'+input_color_filter(plan,item,a,folder,s if panel else None)+
                f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,trim=duration={s["duration"]},setpts=PTS-STARTPTS[v{i}]')
        if panel:
            filters.append(f'color=black:s={w}x{h}:r={fps}:d={s["duration"]}[bg]');prev='bg'
            pw=round(w*.30/2)*2;ph=round(h*.86/2)*2
            for i,item in enumerate(items):
                filters.append(f'[v{i}]crop={pw}:{ph}:(iw-{pw})/2:(ih-{ph})/2[c{i}]')
                x=round((w-pw)/2+item['panel']*.33*w);y=round((h-ph)/2)
                filters.append(f'[{prev}][c{i}]overlay={x}:{y}:shortest=1[p{i}]');prev=f'p{i}'
        else:prev='v0'
        if s.get('zoom'):
            z0,z1=s['zoom'];frames=max(2,round(s['duration']*fps))
            filters.append(f"[{prev}]zoompan=z='{z0}+({z1}-{z0})*on/{frames-1}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}[zoom]");prev='zoom'
        if s.get('fade_out'):
            filters.append(f'[{prev}]fade=t=out:st={max(0,s["duration"]-s["fade_out"])}:d={s["fade_out"]}[fade]');prev='fade'
        # Intermediate picture cuts are losslessly compressed FFV1. Titles,
        # foreground motion and the only lossy encode happen after concatenation.
        filters.append(f'[{prev}]scale=in_range=auto:out_range=tv:out_color_matrix=bt709,format=yuv444p10le,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[finished]')
        prev='finished'
        cmd+=['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map',f'[{prev}]','-an','-frames:v',round(s['duration']*fps),
              '-c:v','ffv1','-level','3','-threads',cfg['ffmpeg_threads'],'-pix_fmt','yuv444p10le',
              '-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-y',dest]
        run(cmd,cwd=str(folder),timeout=7200);clips.append(dest)
    concat=work/'concat.txt';concat.write_text('\n'.join("file '"+p.name+"'" for p in clips),encoding='utf8')
    picture=work/'picture.mkv'
    run([cfg['ffmpeg'],'-v','error','-f','concat','-safe','0','-i',concat,'-c','copy','-y',picture])
    movie=folder/'预览.mp4'
    cmd=[cfg['ffmpeg'],'-v','error','-i',picture,'-i',folder/'混音.wav']
    # Matroska stores millisecond timestamps: many one-frame 30/60 fps cuts
    # accumulate rounding drift. Every cut already contains its exact frame
    # count, so rebuild PTS from decoded frame indices BEFORE any fps filter.
    filters=[f'[0:v]settb=expr=1/{fps},setpts=N[base]'];prev='base'
    from .visual_layers import normalized_layers,position_expression
    for i,layer in enumerate(normalized_layers(plan)):
        asset=assets[layer['id']];input_index=i+2
        if asset['kind']=='image':cmd+=['-loop','1','-framerate',fps,'-i',asset['video']]
        else:cmd+=['-ss',layer['source_in'],'-i',asset['video']]
        metadata=asset.get('source_metadata',{});sw,sh=metadata['width'],metadata['height']
        fit=min(w/sw,h/sh)*layer['scale'];lw,lh=max(1,round(sw*fit)),max(1,round(sh*fit))
        frames=round(layer['duration']*fps);start_frame=round(layer['start']*fps)
        filters.append(f'[{input_index}:v]setpts=(PTS-STARTPTS)/{layer["speed"]},fps={fps},'+input_color_filter(plan,layer,asset,folder)+
            f'format=rgba,scale={lw}:{lh}:flags=lanczos,setsar=1,trim=end_frame={frames},settb=expr=1/{fps},setpts=N+{start_frame}[layer{i}]')
        x=position_expression(layer,'x');y=position_expression(layer,'y')
        end=layer['start']+layer['duration']
        filters.append(f"[{prev}][layer{i}]overlay=x='(W-w)/2+W/2*({x})':y='(H-h)/2-H/2*({y})':"
            f"enable='gte(t,{layer['start']:.12g})*lt(t,{end:.12g})':eval=frame:eof_action=pass:repeatlast=0:format=auto[composite{i}]")
        prev=f'composite{i}'
    m=plan.get('mask_reveal')
    if m:
        a=m.get('start',0);d=m.get('duration',.7);hold=m.get('hold',d*.25)
        t=f'clip((t-{a+hold:.12g})/{d-hold:.12g},0,1)'
        # Crop after RGB conversion so an odd half-height is not rounded down
        # by the color source's default YUV 4:2:0 format.
        filters.append(f'color=black:s={w}x{h}:r={fps}:d={plan["duration"]},format=rgba,crop={w}:{h//2}:0:0[top]')
        filters.append(f'color=black:s={w}x{h}:r={fps}:d={plan["duration"]},format=rgba,crop={w}:{h//2}:0:0[bottom]')
        enable=f"gte(t,{a:.12g})*lt(t,{a+d:.12g})"
        filters.append(f"[{prev}][top]overlay=x=0:y='-{h//2}*{t}':enable='{enable}':format=auto[mt]")
        filters.append(f"[mt][bottom]overlay=x=0:y='{h//2}+{h//2}*{t}':enable='{enable}':format=auto[mb]");prev='mb'
    filters.append(f'[{prev}]ass=preview.ass:fontsdir=assets/fonts,scale=in_range=auto:out_range=tv:out_color_matrix=bt709,format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[finished]')
    # Filter scripts avoid Windows command-line length limits for many moving layers.
    filter_path=work/'final-filter.txt';filter_path.write_text(';'.join(filters),encoding='utf8')
    cmd+=['-filter_complex_threads','1','-filter_complex_script',filter_path,'-map','[finished]','-map','1:a:0',
          '-c:v','libx264','-threads',cfg['ffmpeg_threads'],'-preset',quality['preset'],'-crf',quality['crf'],
          '-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',
          '-r',fps,'-fps_mode','cfr','-frames:v',round(plan['duration']*fps),'-c:a','aac','-b:a','320k','-t',plan['duration'],'-movflags','+faststart','-y',movie]
    run(cmd,cwd=str(folder),timeout=7200)
    run([cfg['ffmpeg'],'-v','error','-i',movie,'-f','null','-'],timeout=1800)
    measured=probe(movie,cfg)
    frame_info=json.loads(run([cfg['ffprobe'],'-v','error','-select_streams','v:0','-show_entries','stream=nb_frames','-of','json',movie]).stdout)
    reported_frames=next(iter(frame_info.get('streams',[])),{}).get('nb_frames')
    frame_count=int(reported_frames) if str(reported_frames).isdigit() else 0
    if frame_count!=round(plan['duration']*fps):
        raise EditError('PREVIEW_FRAME_MISMATCH','预览帧数与计划不一致，未通过导出验收。',{'expected':round(plan['duration']*fps),'actual':frame_count})
    if (measured['width'],measured['height'])!=(w,h):
        raise EditError('PREVIEW_SIZE_MISMATCH','预览分辨率与计划不一致。',measured)
    from .sound import write_audio_qc
    audio_qc=write_audio_qc(folder,cfg,preview_encoded=movie)
    quality.update(codec='h264',pixel_format=measured['pix_fmt'],video_encodes_per_frame=2,frame_count=frame_count,
        intermediate_codec='ffv1',intermediate_compression_lossless=True,lossy_video_encodes_per_frame=1,
        lossless=False,color_output='SDR',fps=fps,measured=measured,
        color_report=str(folder/'color-report.json') if (folder/'color-report.json').is_file() else None,
        audio_qc_path=str(folder/'audio-qc.json'),audio_qc=audio_qc,
        hdr_tonemapped_preview_only=[k for k,a in assets.items() if a.get('source_metadata',{}).get('color_transfer') in ('arib-std-b67','smpte2084')],
        note='高画质预览仍需编码；剪映工程使用原片。最终成片请在剪映选择匹配原素材的分辨率、帧率、码率与 HDR 设置。')
    write(folder/'preview-quality.json',quality)
    return movie


def write_ass(plan,folder,w,h):
    from .typography import text_style,caption_line
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,24,&H00EBF5F7,&H000000FF,&H0015100B,&H80000000,0,0,0,0,100,100,0,0,1,1.5,0,5,25,25,25,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events=[]
    for kind in ('captions','titles'):
        for item in plan.get(kind,[]):
            for line,(lang,text) in enumerate(text_items(item)):
                cap=kind=='captions'
                if cap:line=caption_line(plan,item,lang)
                sty=text_style(item,cap,line,lang);x=item.get('x',0) if not cap else 0;y=sty['y']
                if abs(x)>2:x=(x-plan['width']/2)/(plan['width']/2)
                if abs(y)>2:y=(plan['height']/2-y)/(plan['height']/2)
                px=(x+1)*w/2;py=(1-y)*h/2;size=sty['size']
                if size>30:size/=7
                preview_size=max(16*h/540,size*7*h/1440) if cap else size*7*h/1440
                tags=f'\\an5\\fs{preview_size:.2f}\\pos({px:.1f},{py:.1f})\\b{int(sty["bold"])}'
                if not cap and item.get('animate',True):tags=f'\\an5\\fs{size*7*h/1440:.2f}\\move({px:.1f},{py+h*.0175:.1f},{px:.1f},{py:.1f},0,240)\\b{int(sty["bold"])}'
                def asscolor(rgb):return '&H'+''.join(f'{round(v*255):02X}' for v in reversed(rgb))+'&'
                family=sty['font'].get('preview_family',sty['font'].get('family','Microsoft YaHei')).replace('\\','').replace('{','').replace('}','')
                tags+=f'\\fn{family}\\c{asscolor(sty["color"])}\\3c{asscolor(sty["outline"])}\\bord{0.3 if sty["border_width"] else 0}\\shad0.4'
                if item.get('rotation'):tags+=f'\\frz{-item["rotation"]}'
                text=text.replace('\\','\\\\').replace('{','\\{').replace('}','\\}').replace('\n','\\N')
                events.append(f'Dialogue: {1 if cap else 2},{timecode(item["start"],True)},{timecode(item["end"],True)},Default,,0,0,0,,{{{tags}}}{text}')
    (folder/'preview.ass').write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')

"""Bounded-disk full-quality rendering: decode -> raw pipe -> one final MP4 encode.
No editor dependency, compressed intermediates, or source movie copies.
"""
from __future__ import annotations
import json, os, re, subprocess, time
from .common import EditError, progress

PROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
from pathlib import Path


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def strs(cmd):
    return [str(x) for x in cmd]

def hdr_filter(asset):
    if asset.get('source_metadata',{}).get('color_transfer') in ('arib-std-b67','smpte2084'):
        return 'zscale=t=linear:npl=100,format=gbrpf32le,tonemap=tonemap=mobius:desat=0,zscale=p=bt709:t=bt709:m=bt709:r=tv,'
    return ''

def nframes(duration,fps):
    n=round(duration*fps)
    if abs(duration*fps-n)>0.002:
        raise ValueError(f'Time {duration} does not align to {fps} fps')
    return n

def progress_frames(path):
    txt=Path(path).read_text(encoding='utf-8',errors='replace') if Path(path).exists() else ''
    matches=re.findall(r'^frame=(\d+)$',txt,re.M)
    return int(matches[-1]) if matches else None

def producer(plan, assets, shot, cfg, work, seq):
    w,h,fps=plan['width'],plan['height'],plan['fps']
    cmd=[cfg['ffmpeg'],'-hide_banner','-nostats','-nostdin','-v','error']
    panels=[p for p in plan.get('panels',[]) if p['index']==shot['index']]
    items=panels or [shot]
    for item in items:
        a=assets[item['id']]
        if a['kind']=='image':cmd+=['-loop','1','-framerate',fps,'-i',a['video']]
        else:cmd+=['-ss',item['source_in'],'-threads',cfg.get('ffmpeg_threads',2),'-i',a['video']]
    filters=[]
    for i,item in enumerate(items):
        a=assets[item['id']]
        filters.append(f'[{i}:v]setpts=(PTS-STARTPTS)/{item["speed"]},fps={fps},'+hdr_filter(a)+
            f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,trim=duration={shot["duration"]},setpts=PTS-STARTPTS[v{i}]')
    if panels:
        filters.append(f'color=black:s={w}x{h}:r={fps}:d={shot["duration"]}[bg]');prev='bg'
        pw=round(w*.30/2)*2;ph=round(h*.86/2)*2
        for i,item in enumerate(items):
            filters.append(f'[v{i}]crop={pw}:{ph}:(iw-{pw})/2:(ih-{ph})/2[c{i}]')
            x=round((w-pw)/2+item['panel']*.33*w);y=round((h-ph)/2)
            filters.append(f'[{prev}][c{i}]overlay={x}:{y}:shortest=1[p{i}]');prev=f'p{i}'
    else:prev='v0'
    if shot.get('zoom'):
        z0,z1=shot['zoom'];frames=max(2,nframes(shot['duration'],fps))
        filters.append(f"[{prev}]zoompan=z='{z0}+({z1}-{z0})*on/{frames-1}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps={fps}[zoom]");prev='zoom'
    if shot.get('fade_out'):
        filters.append(f'[{prev}]fade=t=out:st={max(0,shot["duration"]-shot["fade_out"])}:d={shot["fade_out"]}[fade]');prev='fade'
    filters.append(f'[{prev}]scale=in_range=auto:out_range=tv:out_color_matrix=bt709,format=yuv444p10le,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[finished]')
    filter_path=work/f'shot-{seq:04d}-filter.txt';filter_path.write_text(';'.join(filters),encoding='utf-8')
    progress_path=work/f'shot-{seq:04d}-progress.txt'
    cmd+=['-filter_complex_threads','1','-filter_complex_script',filter_path,'-map','[finished]','-an','-frames:v',nframes(shot['duration'],fps),
        '-c:v','rawvideo','-threads','1','-pix_fmt','yuv444p10le','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',
        '-progress',progress_path,'-f','rawvideo','pipe:1']
    return strs(cmd),progress_path

def encoder_args(cfg):
    # Deterministic software encoding works without a vendor driver or editor.
    return ['-c:v', 'libx264', '-threads', str(cfg.get('ffmpeg_threads', 4)),
            '-preset', 'medium', '-crf', '16']

def final_command(plan,assets,folder,cfg,work,out):
    from .visual_layers import normalized_layers,position_expression
    w,h,fps=plan['width'],plan['height'],plan['fps']
    cmd=[cfg['ffmpeg'],'-hide_banner','-nostats','-nostdin','-v','error','-f','rawvideo','-pixel_format','yuv444p10le','-video_size',f'{w}x{h}','-framerate',fps,
        '-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-i','pipe:0','-i',folder/'混音.wav']
    filters=[f'[0:v]settb=expr=1/{fps},setpts=N[base]'];prev='base'
    for i,layer in enumerate(normalized_layers(plan)):
        asset=assets[layer['id']];input_index=i+2
        if asset['kind']=='image':cmd+=['-loop','1','-framerate',fps,'-i',asset['video']]
        else:cmd+=['-ss',layer['source_in'],'-threads',cfg.get('ffmpeg_threads',2),'-i',asset['video']]
        sw,sh=asset['source_metadata']['width'],asset['source_metadata']['height']
        fit=min(w/sw,h/sh)*layer['scale'];lw,lh=max(1,round(sw*fit)),max(1,round(sh*fit))
        frames=nframes(layer['duration'],fps);start_frame=nframes(layer['start'],fps)
        filters.append(f'[{input_index}:v]setpts=(PTS-STARTPTS)/{layer["speed"]},fps={fps},'+hdr_filter(asset)+
            f'format=rgba,scale={lw}:{lh}:flags=lanczos,setsar=1,trim=end_frame={frames},settb=expr=1/{fps},setpts=N+{start_frame}[layer{i}]')
        x=position_expression(layer,'x');y=position_expression(layer,'y');end=layer['start']+layer['duration']
        filters.append(f"[{prev}][layer{i}]overlay=x='(W-w)/2+W/2*({x})':y='(H-h)/2-H/2*({y})':enable='gte(t,{layer['start']:.12g})*lt(t,{end:.12g})':eval=frame:eof_action=pass:repeatlast=0:format=auto[composite{i}]")
        prev=f'composite{i}'
    m=plan.get('mask_reveal')
    if m:
        a=m.get('start',0);d=m.get('duration',.7);hold=m.get('hold',d*.25)
        t=f'clip((t-{a+hold:.12g})/{d-hold:.12g},0,1)'
        filters.append(f'color=black:s={w}x{h}:r={fps}:d={plan["duration"]},format=rgba,crop={w}:{h//2}:0:0[top]')
        filters.append(f'color=black:s={w}x{h}:r={fps}:d={plan["duration"]},format=rgba,crop={w}:{h//2}:0:0[bottom]')
        enable=f'gte(t,{a:.12g})*lt(t,{a+d:.12g})'
        filters.append(f"[{prev}][top]overlay=x=0:y='-{h//2}*{t}':enable='{enable}':format=auto[mt]")
        filters.append(f"[mt][bottom]overlay=x=0:y='{h//2}+{h//2}*{t}':enable='{enable}':format=auto[mb]");prev='mb'
    filters.append(f'[{prev}]ass=preview.ass:fontsdir=assets/fonts,scale=in_range=auto:out_range=tv:out_color_matrix=bt709,format=yuv420p,setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709[finished]')
    filter_path=work/'final-filter.txt';filter_path.write_text(';'.join(filters),encoding='utf-8')
    cmd+=['-filter_complex_threads','1','-filter_complex_script',filter_path,'-map','[finished]','-map','1:a:0',*encoder_args(cfg),
        '-pix_fmt','yuv420p','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',
        '-r',fps,'-fps_mode','cfr','-frames:v',nframes(plan['duration'],fps),'-c:a','aac','-b:a','320k','-ar','48000','-ac','2','-t',plan['duration'],
        '-movflags','+faststart','-progress',work/'final-progress.txt','-n',out]
    return strs(cmd)

def verify_streams(measured, plan):
    streams=measured.get('streams',[])
    videos=[s for s in streams if s.get('codec_type')=='video']
    audios=[s for s in streams if s.get('codec_type')=='audio']
    if len(videos)!=1 or len(audios)!=1:
        raise RuntimeError('Final MP4 must contain one video and one prepared-mix audio stream')
    video,audio=videos[0],audios[0]
    expected=nframes(plan['duration'],plan['fps']);actual=int(video.get('nb_frames',0))
    rate=video.get('avg_frame_rate','0/1').split('/')
    fps=float(rate[0])/float(rate[1]) if len(rate)==2 and float(rate[1]) else 0
    if (actual!=expected or (video['width'],video['height'])!=(plan['width'],plan['height'])
            or abs(fps-plan['fps'])>.00001):
        raise RuntimeError('Final frame count/resolution/frame rate mismatch')
    # AAC is stored in 1024-sample frames; tolerate one codec frame at the end,
    # never accept missing/truncated audio solely because picture decodes.
    tolerance=1024/48000+.002
    if (audio.get('codec_name')!='aac' or str(audio.get('sample_rate'))!='48000'
            or audio.get('channels')!=2
            or abs(float(audio.get('duration',0))-plan['duration'])>tolerance
            or abs(float(audio.get('start_time',0)))>tolerance):
        raise RuntimeError('Final AAC mix format, start time or duration mismatch')
    return actual

def render(plan,assets,folder,cfg,out):
    work = folder / 'render-work'
    from .preview import write_ass
    folder=folder.resolve();out=out.resolve();work=work.resolve()
    if out.exists():raise ValueError('Output exists; refusing overwrite')
    work.mkdir(parents=True,exist_ok=False)
    if plan.get('custom_source_crops'):raise ValueError('Legacy custom_source_crops must be migrated before this renderer')
    fps=plan['fps'];expected=nframes(plan['duration'],fps)
    if sum(nframes(s['duration'],fps) for s in plan['shots'])!=expected:raise ValueError('Shot frame counts do not match timeline')
    cursor=0
    for s in plan['shots']:
        if nframes(s['start'],fps)!=cursor:raise ValueError('Non-contiguous shot starts')
        cursor+=nframes(s['duration'],fps)
    if not (folder/'混音.wav').is_file():raise ValueError('Missing prepared mix WAV')
    write_ass(plan,folder,plan['width'],plan['height'])
    commands=[];shot_counts=[];partial=out.with_name(out.stem+'.partial.mp4')
    if partial.exists():raise ValueError('Partial output exists; refusing overwrite')
    cmd=final_command(plan,assets,folder,cfg,work,partial)
    commands.append({'role':'final_single_lossy_encode','args':cmd})
    save(work/'commands.json',commands)
    started=time.time();enc=None
    try:
        with (work/'final-stderr.txt').open('wb') as enc_log:
            enc=subprocess.Popen(cmd,cwd=folder,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=enc_log,bufsize=0,creationflags=PROCESS_FLAGS)
            for seq,shot in enumerate(plan['shots'],1):
                if enc.poll() is not None:raise RuntimeError(f'Final encoder exited early ({enc.returncode})')
                cmd,progress_path=producer(plan,assets,shot,cfg,work,seq)
                commands.append({'role':'uncompressed_shot_producer','sequence':seq,'shot_index':shot['index'],'expected_frames':nframes(shot['duration'],fps),'args':cmd})
                save(work/'commands.json',commands)
                progress(f'渲染镜头 {seq}/{len(plan["shots"])}…')
                with (work/f'shot-{seq:04d}-stderr.txt').open('wb') as shot_log:
                    p=subprocess.Popen(cmd,cwd=folder,stdout=enc.stdin,stderr=shot_log,creationflags=PROCESS_FLAGS)
                    try:code=p.wait(timeout=1800)
                    except BaseException:
                        p.kill();p.wait();raise
                actual=progress_frames(progress_path);want=nframes(shot['duration'],fps)
                shot_counts.append({'sequence':seq,'index':shot['index'],'expected':want,'actual':actual,'returncode':code})
                save(work/'shot-frame-counts.json',shot_counts)
                if code or actual!=want:raise RuntimeError(f'Shot {seq} failed or underflow: code={code}, frames={actual}/{want}')
            enc.stdin.close()
            code=enc.wait(timeout=1800)
            if code:raise RuntimeError(f'Final encoder failed: code={code}')
        probe_cmd=strs([cfg['ffprobe'],'-v','error','-show_streams','-show_format','-of','json',partial])
        measured=json.loads(subprocess.run(probe_cmd,capture_output=True,check=True,timeout=120,creationflags=PROCESS_FLAGS).stdout)
        actual=verify_streams(measured,plan)
        decode_cmd=strs([cfg['ffmpeg'],'-v','error','-i',partial,'-f','null','-'])
        decoded=subprocess.run(decode_cmd,capture_output=True,timeout=7200,creationflags=PROCESS_FLAGS)
        if decoded.returncode or decoded.stderr.strip():raise RuntimeError('Full decode check failed: '+decoded.stderr.decode('utf-8',errors='replace')[-2000:])
        from .assets import verify_referenced_sources
        verify_referenced_sources(folder)
        report={'success':True,'output':str(out),'duration':plan['duration'],'width':plan['width'],'height':plan['height'],'fps':fps,'frame_count':actual,
            'encoder':'libx264', 'crf':16, 'preset':'medium','intermediate_codec':'rawvideo yuv444p10le, streamed through OS pipe','intermediate_compressed':False,
            'persistent_video_intermediates':False,'lossy_video_encodes_per_output_frame':1,'original_video_modified':False,'full_decode_verified':True,
            'elapsed_seconds':round(time.time()-started,3),'command_log':str(work/'commands.json'),'shot_frame_counts':shot_counts,
            'measured':measured,'notes':['Originals decoded only; no compressed intermediate video.','Composition, scaling, frame-rate conversion and SDR/HDR transforms can change pixels; final H.264 MP4 is not lossless.','ASS titles and subtitles are rendered after visual composition.','All original audio handling is represented by supplied mix WAV; this renderer never imports camera audio.']}
        # Report-write failures must not leave a file named as a completed movie.
        save(work/'render-quality.json',report)
        if out.exists():raise RuntimeError('Output appeared during rendering; refusing overwrite')
        partial.rename(out)
        return report
    except BaseException as exc:
        if enc and enc.poll() is None:
            try:enc.stdin.close()
            except (OSError,ValueError):pass
            enc.kill();enc.wait()
        save(work/'failure.json',{'error':repr(exc),'partial':str(partial),'commands':str(work/'commands.json'),'shot_frame_counts':shot_counts})
        raise EditError('MP4_RENDER_FAILED', 'MP4 渲染未完成，请查看失败记录后生成新版本。', {'work': str(work), 'cause': str(exc)}) from exc


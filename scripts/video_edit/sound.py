from __future__ import annotations
import math
import wave
from pathlib import Path
from .common import *

SR=48000

def pcm(path):
    import numpy as np
    with wave.open(str(path),'rb') as w:
        if w.getnchannels()!=2 or w.getsampwidth()!=2 or w.getframerate()!=SR:
            raise EditError('AUDIO_FORMAT','内部音频需要 48kHz 立体声 PCM。')
        return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype(np.float32).reshape(-1,2)/32768

def wavwrite(path,a):
    import numpy as np
    with wave.open(str(path),'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR)
        w.writeframes((np.clip(a,-1,1)*32767).astype('<i2').tobytes())

def compose(path,duration,rhythm):
    """Procedural instrumental bed; no third-party music is redistributed."""
    import numpy as np
    bpm=104 if rhythm=='轻快活泼' else 80
    beat=60/bpm; n=round((duration+1)*SR); out=np.zeros(n,np.float32)
    bright=rhythm=='轻快活泼'
    chords=[(60,64,67),(57,60,64),(53,57,60),(55,59,62)]
    for b in range(math.ceil((duration+1)/beat)):
        chord=chords[(b//4)%4];note=chord[b%3]+(12 if bright else 0)
        freq=440*2**((note-69)/12);length=min(beat*1.8,1.2)
        t=np.arange(round(length*SR))/SR
        tone=(np.sin(2*np.pi*freq*t)+.22*np.sin(4*np.pi*freq*t))*np.exp(-4*t/length)*np.minimum(1,t/.008)*.10
        start=round(b*beat*SR);end=min(n,start+len(tone));out[start:end]+=tone[:end-start]
        if b%4==0:
            t=np.arange(round(beat*3.9*SR))/SR
            pad=sum(np.sin(2*np.pi*440*2**((q-81)/12)*t) for q in chord)/3
            pad=pad*.07*np.minimum(t/.12,1)*np.minimum((t[-1]-t)/.3,1)
            end=min(n,start+len(pad));out[start:end]+=pad[:end-start]
        if bright:
            t=np.arange(round(.12*SR))/SR
            kick=np.sin(2*np.pi*(65*t-90*t*t))*np.exp(-35*t)*.06
            end=min(n,start+len(kick));out[start:end]+=kick[:end-start]
    wavwrite(path,np.column_stack([out,out]))
    return {'source':'procedural','bpm':bpm,'beats':[round(k*beat,6) for k in range(math.ceil(duration/beat))],
            'license':'本工具程序生成的伴奏；不包含第三方录音。','quality_note':'简单循环伴奏，可替换为用户喜欢的音乐。'}

def detect_beats(path):
    """Spectral-flux onset estimates, not a claim of exact musical downbeats."""
    import numpy as np
    mono=pcm(path).mean(axis=1)[::4];sr=SR/4;hop=256;window=1024
    previous=None;flux=[]
    for start in range(0,max(0,len(mono)-window),hop):
        spectrum=np.abs(np.fft.rfft(mono[start:start+window]*np.hanning(window)))
        flux.append(0 if previous is None else float(np.maximum(spectrum-previous,0).sum()))
        previous=spectrum
    a=np.array(flux)
    if len(a)<3 or a.max()<1e-8:return {'source':'spectral_flux','beats':[],'confidence':'low'}
    threshold=float(np.median(a)+np.std(a)*.75);peaks=[]
    for i in range(1,len(a)-1):
        t=i*hop/sr
        if a[i]>threshold and a[i]>=a[i-1] and a[i]>a[i+1] and (not peaks or t-peaks[-1]>.25):peaks.append(round(t,4))
    return {'source':'spectral_flux','beats':peaks,'confidence':'candidate_onsets','note':'候选重音需听审，不能当作精确小节线。'}

def speech(text,path,gender,language,cfg):
    request=path.with_suffix('.speech.json')
    write(request,{'text':text,'output':str(path),'gender':gender,'language':language})
    try:
        run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'scripts/speak.ps1','-Request',request],timeout=180)
    except EditError as exc:
        raise EditError('VOICE_UNAVAILABLE','离线配音未成功。请选择电脑已有的语言声音，或关闭配音。',exc.details)
    normalized=path.with_name(path.stem+'_48k.wav')
    run([cfg['ffmpeg'],'-v','error','-i',path,'-ac','2','-ar',SR,'-y',normalized])
    return normalized

def prepare_audio(plan,assets,folder,cfg):
    import numpy as np
    from .audio_policy import validate_original_audio, original_audio_window, render_review_audio
    errors=[]
    validate_original_audio(plan,[dict(a,id=ident) for ident,a in assets.items()],
                            lambda code,where,message:errors.append({'code':code,'at':where,'message':message}))
    if errors:raise EditError('ORIGINAL_AUDIO_REVIEW_FAILED','原声审核未通过：重新试听需要的片段，或将其静音。',{'errors':errors})
    audio=folder/'assets/audio';audio.mkdir(parents=True,exist_ok=True)
    events=[];voices=[];warnings=[];original_reviews=[];total=plan['duration'];request=plan.get('request',{})
    def event(path,start,duration,source_in=0,gain=1,track='original',fi=.05,fo=.12,keys=None):
        e={'path':str(path),'start':start,'duration':duration,'source_in':source_in,'gain':gain,
           'fade_in':min(fi,duration),'fade_out':min(fo,duration),'track':track,'keys':keys or []}
        events.append(e);return e
    for s in plan['shots']:
        if str(s.get('purpose','')).startswith('panels_'):continue
        a=assets[s['id']]
        report={'index':s['index'],'id':s['id'],'decision':'muted','gain':s.get('audio_gain',0)}
        original_reviews.append(report)
        if not a.get('audio') or s.get('audio_gain',0)==0:
            report['reason']='默认静音或明确静音；变速原声不输出。' if a.get('audio') else '无原音轨。'
            continue
        review=s['audio_review'];window=original_audio_window(s,total,a['duration'])
        path=audio/f'现场_{s["index"]:04d}.wav'
        rendered=render_review_audio(a['audio'],path,window['source_start'],window['source_end'],cfg,review.get('denoise'))
        e=event(path,window['start'],window['duration'],gain=s['audio_gain'])
        e['speech']=review['purpose']=='key_speech'
        report.update(decision='kept',review=review,window=window,filter_applied=rendered['filter_applied'],
                      processing_verified=True,quality_note='执行已记录的处理；音质合格依据来自实际试听记录。')
    for i,n in enumerate(plan.get('narration',[]) if request.get('voiceover') else []):
        raw_path=audio/f'故事配音_{i:03d}.wav'
        p=speech(n['text'],raw_path,request.get('voice_gender','女声'),n.get('language','zh-CN'),cfg)
        voice=read(str(raw_path)+'.voice.json');voices.append(dict(voice,start=n['start'],language=n.get('language','zh-CN')))
        wanted='Male' if request.get('voice_gender')=='男声' else 'Female'
        if voice.get('gender')!=wanted:
            warnings.append('本机没有所选性别的声音，实际配音使用：'+voice.get('voice','未知音色'))
        # Draft writer probes WAV lengths at millisecond precision. Pad the last
        # fractional millisecond so native editing never trims a spoken ending.
        samples=pcm(p);length=math.ceil(len(samples)/48)/1000
        count=round(length*SR)
        if count>len(samples):wavwrite(p,np.pad(samples,((0,count-len(samples)),(0,0))))
        if length>n['end']-n['start']+.03:
            raise EditError('NARRATION_TOO_LONG','配音长于预留时间，请缩短文案或延长对应镜头，不能截断讲话。',{'index':i,'audio_seconds':length,'slot_seconds':n['end']-n['start']})
        event(p,n['start'],length,gain=.9,track='voiceover')
    from .audio_layers import prepare_layers, duck_background
    layer_report=prepare_layers(plan,audio,cfg,event)
    music_info=None
    if request.get('music','自动配乐')!='只保留原声' and not any(e['track']=='music' for e in events):
        music=folder/'assets/music';music.mkdir(exist_ok=True)
        dest=music/'配乐.wav'
        selected=request.get('music_file')
        if not selected and request.get('music')=='使用我自己的音乐':
            raise EditError('MUSIC_NOT_SELECTED','选择了自己的音乐但没有文件，请选择曲目或改为自动配乐。')
        if not selected and cfg.get('music_library'):
            raise EditError('MUSIC_SELECTION_REQUIRED','音乐库已配置，请先按故事试听选曲并设置 request.music_file 或 audio_layers，不能按文件名字母顺序代选。')
        if selected:
            src=Path(selected)
            if not src.is_file():raise EditError('MUSIC_NOT_FOUND','选择的音乐文件不存在。')
            original=music/('原音乐'+src.suffix);shutil.copy2(src,original)
            run([cfg['ffmpeg'],'-v','error','-stream_loop','-1','-i',src,'-t',total,'-af','loudnorm=I=-20:TP=-2:LRA=11','-ac','2','-ar',SR,'-y',dest])
            music_info=detect_beats(dest);music_info['source_file']=str(original)
        else:music_info=compose(dest,total,request.get('rhythm','温馨舒缓'))
        event(dest,0,total,gain=.55,track='music',fi=.6,fo=min(1.5,total/4))
        write(folder/'music-analysis.json',music_info)
    speech_spans=[(e['start'],e['start']+e['duration']) for e in events
                  if e['track']=='voiceover' or (e['track']=='original' and e.get('speech'))]
    duck_background(events,speech_spans)
    # Float accumulation and a shared linear master gain keep native and preview consistent.
    mix=np.zeros((round(total*SR),2),np.float32)
    for e in events:
        data=pcm(e['path']);a=round(e['source_in']*SR);n=round(e['duration']*SR);piece=data[a:a+n]
        if len(piece)<n:piece=np.pad(piece,((0,n-len(piece)),(0,0)))
        ts=np.arange(n)/SR;env=np.ones(n,dtype=np.float32)*e['gain']
        if e['keys']:env*=np.interp(ts,[k[0] for k in e['keys']],[k[1] for k in e['keys']])
        env*=np.minimum(1,ts/max(e['fade_in'],1/SR))*np.minimum(1,(e['duration']-ts)/max(e['fade_out'],1/SR))
        start=round(e['start']*SR);length=min(n,len(mix)-start)
        if length>0:mix[start:start+length]+=piece[:length]*env[:length,None]
    peak=float(np.max(np.abs(mix))) if len(mix) else 0
    gain=min(1,.85/max(peak,1e-9))
    for e in events:e['gain']*=gain
    wavwrite(folder/'混音.wav',mix*gain)
    result={'events':events,'original_audio':original_reviews,'master_gain':gain,'peak_dbfs':20*math.log10(max(peak*gain,1e-9)),'music':music_info,'audio_layers':layer_report,'voices':voices,'warnings':list(dict.fromkeys(warnings))}
    write(folder/'audio-plan.json',result)
    return result

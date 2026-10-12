from __future__ import annotations
import argparse
import importlib.metadata
import traceback
from .common import *
from . import __version__

class Parser(argparse.ArgumentParser):
    def error(self,message):raise EditError('ARGUMENT_ERROR',message)

def doctor(cfg):
    modules={k:bool(importlib.util.find_spec(k)) for k in ('tkinter','numpy','PIL','fontTools','faster_whisper','pyJianYingDraft')}
    version=None
    try:version=importlib.metadata.version('pyJianYingDraft')
    except importlib.metadata.PackageNotFoundError:pass
    native=modules['pyJianYingDraft'] and bool(cfg.get('jianying_install_dir')) and version=='0.3.0'
    from .native import rectangle_mask
    mask_path=rectangle_mask(cfg,False)
    problems=[]
    applications=None
    if os.name=='nt':
        with tempfile.TemporaryDirectory(prefix='video-edit-apps-') as tmp:
            app_result=Path(tmp)/'applications.json'
            app_config=Path(tmp)/'machine.json';write(app_config,cfg)
            try:run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'scripts/application-worker.ps1','-Root',ROOT,'-Result',app_result,'-ConfigPath',app_config],timeout=30)
            except EditError:
                if not app_result.is_file():problems.append('软件检测未完成，请在本机运行安装向导第一步。')
            if app_result.is_file():
                applications=read(app_result)
                if not applications.get('ready'):problems.append('剪映或 DeepSeek Harness 尚未安装，请运行安装向导第一步获取官方安装包。')
    for key in ('ffmpeg','ffprobe'):
        if not cfg[key]:problems.append(f'没有找到 {key}')
    for key in ('tkinter','numpy','PIL','fontTools'):
        if not modules[key]:problems.append('缺少 Python 组件：'+key)
    if not native:problems.append('剪映原生导出需要已安装的剪映和固定版本草稿库。')
    if not modules['faster_whisper'] or not model_path(cfg):problems.append('本地语音识别组件或模型缺失，请运行自动配置环境。')
    if not Path(cfg['font_path']).is_file():problems.append('配置中的字体文件已不存在，请运行自动配置环境恢复系统字体。')
    voices=[]
    from .typography import fonts,PRESETS
    catalog=fonts(cfg) if modules['PIL'] else {}
    graphical=False;graphical_error=None
    if modules['tkinter']:
        try:
            run([sys.executable,'-c','import tkinter as t;r=t.Tk();r.withdraw();r.update_idletasks();r.destroy()'],timeout=20)
            graphical=True
        except Exception as exc:
            graphical_error=str(exc)
            problems.append('图形组件不能在当前执行环境启动；请在本机桌面运行，受限 Harness 需允许本地窗口访问。')
    if os.name=='nt':
        try:
            p=run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',ROOT/'scripts/voices.ps1'],timeout=30)
            voices=json.loads(p.stdout.decode('utf-8-sig'))
        except Exception:pass
    return {'ready':not problems,'python':sys.executable,'python_version':sys.version.split()[0],
            'applications':applications,
            'dependencies':modules,'writer_version':version,'ffmpeg':cfg['ffmpeg'],'ffprobe':cfg['ffprobe'],
            'jianying_install_dir':cfg['jianying_install_dir'],'whisper_model':model_path(cfg),'offline_voices':voices,
            'graphical_error':graphical_error,
            'typography':{'presets':list(PRESETS),'installed_font_count':len(catalog),
                'available_families':sorted({v['family'] for v in catalog.values()},key=str.casefold),
                'curated_fonts':[v for v in catalog.values() if v.get('curated')],
                'font_files_bundled':any(v.get('curated') for v in catalog.values())},
            'rectangle_mask_dir':mask_path,
            'quality':{'native_media':'byte_identical_originals','default_policy':'preserve_source',
                       'preview_mode':cfg.get('preview_mode','full_quality'),'preview_lossless':False,
                       'preview_color_output':'SDR','source_hdr_preserved':True},
            'capabilities':{'native_editable_draft':native,'graphical_wizard':graphical,'local_transcription':bool(model_path(cfg)) and modules['faster_whisper'],
                'segmented_speed':native,'editable_masks':native and bool(mask_path),'independent_text_audio':native,
                'explicit_audio_layers':native,'dense_frame_evidence':True,
                'host_delegation':'由当前宿主实际暴露的委派工具决定，doctor 不检测模型权限',
                'semantic_selection':'Harness 必须查看抽样画面和转录后作出判断','optical_flow':False,'motion_tracking':False,'complex_matting':False,'continuous_speed_curve':False},
            'problems':problems,'note':'ready 仅表示运行依赖就绪；不等于剪映界面和 Harness 加载验收已通过。'}

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8')
    parser=Parser(description='video-edit：旅行、家庭和活动纪念片工具')
    parser.add_argument('--version',action='version',version=__version__)
    sub=parser.add_subparsers(dest='command',required=True,parser_class=Parser)
    for command in ('doctor','analyze','validate','export-jianying'):
        p=sub.add_parser(command);p.add_argument('--config');p.add_argument('--result',help='另存结构化返回结果')
        if command=='analyze':
            p.add_argument('--media');p.add_argument('--request');p.add_argument('--output');p.add_argument('--wizard',action='store_true')
            p.add_argument('--no-transcribe',action='store_true');p.add_argument('--no-reuse',action='store_true');p.add_argument('--request-only',action='store_true')
        elif command=='validate':p.add_argument('--plan',required=True)
        elif command=='export-jianying':
            p.add_argument('--plan');p.add_argument('--output');p.add_argument('--name');p.add_argument('--register',action='store_true')
            p.add_argument('--no-preview',action='store_true');p.add_argument('--relocate',help='修复已经移动的工程包，保留编辑器修改')
    args=None;code=0
    try:
        args=parser.parse_args();cfg=load_config(args.config)
        if args.command=='doctor':
            data=doctor(cfg);code=0 if data['ready'] else 2
            result={'ok':data['ready'],'code':'OK' if data['ready'] else 'DEPENDENCIES_MISSING','data':data}
        elif args.command=='analyze':
            from .wizard import show,DEFAULTS
            request=read(args.request) if args.request else DEFAULTS.copy()
            if args.wizard or (not args.media and not request.get('media_dir')):
                request=show(cfg)
                if request is None:
                    result={'ok':True,'code':'CANCELLED','data':{'cancelled':True,'processing_started':False}}
                    emit(result,args);return
            media=args.media or request.get('media_dir');out=args.output or request.get('output_dir')
            if not out:raise EditError('OUTPUT_REQUIRED','请指定输出目录，或者使用图形向导。')
            request['media_dir']=media;request['output_dir']=str(Path(out).resolve())
            if args.request_only:
                write(Path(out)/'request.json',request);data={'request':str(Path(out).resolve()/'request.json'),'next_action':'继续运行 analyze --request'}
            else:
                from .analysis import analyze
                data=analyze(media,out,request,cfg,not args.no_transcribe,not args.no_reuse)
            result={'ok':True,'code':'NEEDS_EDITORIAL_REVIEW','data':data}
        elif args.command=='validate':
            from .plan import validate
            data=validate(read(args.plan),args.plan,cfg);code=0 if data['valid'] else 2
            result={'ok':data['valid'],'code':'OK' if data['valid'] else 'INVALID_PLAN','data':data}
        else:
            from .native import export,relocate
            if args.relocate:data=relocate(args.relocate,cfg,args.name,args.register)
            else:
                if not args.plan or not args.output:raise EditError('ARGUMENT_ERROR','导出需要 --plan 和 --output，或使用 --relocate。')
                data=export(args.plan,args.output,cfg,args.name,args.register,not args.no_preview)
            result={'ok':True,'code':'OK','data':data}
    except EditError as e:
        code=2;result={'ok':False,'code':e.code,'message':str(e),'data':e.details}
    except KeyboardInterrupt:
        code=130;result={'ok':False,'code':'INTERRUPTED','message':'处理已中止，原始素材未删除。'}
    except Exception as e:
        code=1;progress(traceback.format_exc());result={'ok':False,'code':'UNEXPECTED_ERROR','message':str(e)}
    emit(result,args)
    if code:sys.exit(code)

def emit(result,args):
    if args and args.result:write(args.result,result)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False),flush=True)

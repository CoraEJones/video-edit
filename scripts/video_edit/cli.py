from __future__ import annotations
import argparse
import traceback
from .common import *
from . import __version__

class Parser(argparse.ArgumentParser):
    def error(self,message):raise EditError('ARGUMENT_ERROR',message)

def doctor(cfg,delivery_mode=None,host=None,entry_mode=None):
    from .environment import doctor as inspect_environment
    return inspect_environment(cfg,delivery_mode,host,entry_mode)

def request_config(cfg,request):
    """Match dependency checks to stated features, without inferring ASR from captions."""
    if not isinstance(request,dict):raise EditError('REQUEST_FORMAT','制作需求必须是 JSON 对象。')
    if 'delivery_mode' in request:
        if request['delivery_mode'] not in ('mp4','editable'):
            raise EditError('REQUEST_FORMAT','交付方式需要 mp4 或 editable。')
        cfg['delivery_mode']=request['delivery_mode']
    for field,key in (('voiceover','voiceover_required'),('transcription_required','transcription_required')):
        if field in request:
            if not isinstance(request[field],bool):raise EditError('REQUEST_FORMAT',field+' 需要 true 或 false。')
            cfg[key]=request[field]
    return cfg

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr,'reconfigure'):sys.stderr.reconfigure(encoding='utf-8')
    parser=Parser(description='video-edit：先确认需求，再制作 MP4 或剪映工程')
    parser.add_argument('--version',action='version',version=__version__)
    sub=parser.add_subparsers(dest='command',required=True,parser_class=Parser)
    for command in ('doctor','request-check','confirm-request','analyze','validate','export-mp4','export-jianying'):
        p=sub.add_parser(command);p.add_argument('--config');p.add_argument('--result',help='另存结构化返回结果')
        p.add_argument('--delivery-mode',choices=('mp4','editable'))
        p.add_argument('--host',choices=('auto','codex','deepseek'))
        p.add_argument('--entry-mode',choices=('chat','wizard'))
        if command=='doctor':
            p.add_argument('--request',help='按完整或部分需求检查交付方式、配音和显式语音识别需求；不要求已确认')
        elif command in ('request-check','confirm-request'):
            p.add_argument('--request',required=True)
            if command=='confirm-request':
                p.add_argument('--user-confirmed',action='store_true',help='仅在用户已明确确认展示的制作单后使用，不能代替真实同意')
                p.add_argument('--output',help='另存确认后的需求；省略则更新原需求文件')
        elif command=='analyze':
            p.add_argument('--media');p.add_argument('--request');p.add_argument('--output',help='内部分析任务目录，与已确认交付目录分别保存')
            p.add_argument('--wizard',action='store_true');p.add_argument('--no-transcribe',action='store_true')
            p.add_argument('--no-reuse',action='store_true');p.add_argument('--request-only',action='store_true')
        elif command=='validate':p.add_argument('--plan',required=True)
        elif command in ('export-mp4','export-jianying'):
            p.add_argument('--plan');p.add_argument('--output');p.add_argument('--name')
            if command=='export-jianying':
                p.add_argument('--register',action='store_true');p.add_argument('--no-preview',action='store_true')
                p.add_argument('--relocate',help='修复已经移动的工程包，保留编辑器修改')
    args=None;code=0
    try:
        args=parser.parse_args();cfg=load_config(args.config)
        for key in ('delivery_mode','host','entry_mode'):
            if getattr(args,key,None) is not None:cfg[key]=getattr(args,key)
        if args.command=='doctor':
            if args.request:request_config(cfg,read(resolve_path(args.request)))
            data=doctor(cfg);code=0 if data['ready'] else 2
            result={'ok':data['ready'],'code':'OK' if data['ready'] else 'DEPENDENCIES_MISSING','data':data}
        elif args.command in ('request-check','confirm-request'):
            from .intake import inspect_request,confirm_request
            request=read(resolve_path(args.request))
            if args.command=='confirm-request':
                if not args.user_confirmed:
                    raise EditError('USER_CONFIRMATION_REQUIRED','请先向用户展示制作确认单，获得明确回复后再确认。',inspect_request(request,cfg))
                request=confirm_request(request,user_confirmed=True,method='chat_explicit_reply',cfg=cfg)
                write(resolve_path(args.output or args.request),request)
            data=inspect_request(request,cfg)
            status='OK' if data['ready'] else 'REQUEST_CONFIRMATION_REQUIRED' if data['complete'] else 'NEEDS_REQUEST_DETAILS'
            result={'ok':data['ready'],'code':status,'data':data}
            code=0 if data['ready'] else 2
        elif args.command=='analyze':
            from .intake import inspect_request,require_confirmed_request
            request=read(resolve_path(args.request)) if args.request else {}
            if args.media:
                provided=resolve_path(args.media)
                # Preserve a confirmed equivalent spelling (%ENV%, ~, case, etc.).
                # An actual source change updates the content and invalidates its receipt.
                if not isinstance(request.get('media_dir'),str) or resolve_path(request['media_dir'])!=provided:
                    request['media_dir']=str(provided)
            if args.wizard:
                from .wizard import show
                request=show(cfg,request=request)
                if request is None:
                    result={'ok':True,'code':'CANCELLED','data':{'cancelled':True,'processing_started':False}}
                    emit(result,args);return
            if args.request_only:
                if not args.output:raise EditError('OUTPUT_REQUIRED','请指定用于保存需求单的任务目录 --output。')
                path=resolve_path(args.output)/'request.json';write(path,request)
                data={'request':str(path.resolve()),'intake':inspect_request(request,cfg),'processing_started':False,
                      'next_action':'补问缺失需求、核实路径并展示制作确认单；确认后才运行 analyze。'}
                result={'ok':True,'code':'REQUEST_SAVED','data':data}
            else:
                require_confirmed_request(request,cfg)
                request_config(cfg,request)
                if args.no_transcribe and cfg.get('transcription_required'):
                    raise EditError('TRANSCRIPTION_REQUIRED','需求明确要求语音识别，不能同时使用 --no-transcribe；请先修改需求并重新确认。')
                if not args.output:raise EditError('OUTPUT_REQUIRED','请指定内部分析任务目录 --output，不改变已确认的交付位置。')
                from .analysis import analyze
                data=analyze(request['media_dir'],args.output,request,cfg,not args.no_transcribe,not args.no_reuse)
                result={'ok':True,'code':'NEEDS_EDITORIAL_REVIEW','data':data}
        elif args.command=='validate':
            from .plan import validate
            plan_path=resolve_path(args.plan)
            data=validate(read(plan_path),plan_path,cfg);code=0 if data['valid'] else 2
            result={'ok':data['valid'],'code':'OK' if data['valid'] else 'INVALID_PLAN','data':data}
        elif args.command=='export-mp4':
            if not args.plan or not args.output:raise EditError('ARGUMENT_ERROR','成片导出需要 --plan 和已确认的 --output。')
            from .mp4 import export
            result={'ok':True,'code':'OK','data':export(args.plan,args.output,cfg,args.name)}
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

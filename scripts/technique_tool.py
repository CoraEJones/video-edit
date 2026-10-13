"""Inspect, validate, compile or render typed technique assets; stdout is JSON."""
from pathlib import Path
import argparse,json,sys
from video_edit.common import EditError,load_config,read,write,ROOT
from video_edit.technique_spec import validate,compile_spec,render

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='视频技巧：参数化图层与时间映射，保留原片')
    parser.add_argument('--config');sub=parser.add_subparsers(dest='command',required=True)
    for name in ('validate','compile','render'):
        p=sub.add_parser(name);p.add_argument('--spec',required=True)
        if name!='validate':p.add_argument('--output',required=True,help='新的技巧资产目录')
    p=sub.add_parser('native-capabilities');p.add_argument('--spec',required=True)
    p=sub.add_parser('export-jianying');p.add_argument('--spec',required=True);p.add_argument('--output',required=True);p.add_argument('--name',default='技巧复现');p.add_argument('--allow-derived',action='store_true',help='显式允许局部透明素材或整体合成回退；报告列出烘焙操作')
    p=sub.add_parser('catalog');p.add_argument('--query',default='');p.add_argument('--id');p.add_argument('--limit',type=int,default=10);p.add_argument('--offset',type=int,default=0)
    p=sub.add_parser('recipe');p.add_argument('--name',required=True);p.add_argument('--params',required=True);p.add_argument('--output',required=True)
    p=sub.add_parser('normalize-image');p.add_argument('--source',required=True);p.add_argument('--input-space',required=True,choices=('srgb','embedded_icc'));p.add_argument('--output',required=True)
    args=parser.parse_args()
    try:
        if args.command=='normalize-image':
            from video_edit.image_color import convert_image
            result=convert_image(args.source,args.output,args.input_space)
        elif args.command=='recipe':
            from video_edit.technique_recipes import build
            output=Path(args.output).resolve()
            if output.exists():raise EditError('OUTPUT_EXISTS','参数文件已存在，请使用新文件名。')
            params=Path(args.params).resolve();spec=build(args.name,read(params))
            cfg=load_config(args.config);result=validate(spec,params.parent,cfg)
            if not result['valid']:raise EditError('TECHNIQUE_INVALID','配方参数未通过校验。',result)
            # Keep relative paths anchored to the parameter file, even when
            # the emitted spec is in another directory.
            from video_edit.technique_spec import resolve
            for layer in spec['layers']:
                for obj in (layer['source'],layer.get('mask',{})):
                    for field in ('path','font_path'):
                        if field in obj:obj[field]=str(resolve(obj[field],params.parent))
            write(output,spec);result={'spec':str(output),'validation':result}
        elif args.command=='catalog':
            if not 1<=args.limit<=20 or args.offset<0:raise ValueError('catalog limit needs1..20 and offset must be nonnegative')
            directory=ROOT/'assets/techniques';cards=[]
            if directory.is_dir():
                for path in sorted(directory.glob('*.json')):
                    card=read(path)
                    if args.id:
                        if card['id']==args.id:cards.append(card)
                    elif not args.query or args.query.casefold() in json.dumps(card,ensure_ascii=False).casefold():
                        cards.append({k:card[k] for k in ('id','title','execution_routes')}|{'techniques':[{'id':t['id'],'name':t['name'],'equivalence':t['execution_equivalence']} for t in card['techniques']]})
            if args.id and not cards:raise EditError('LESSON_UNKNOWN','没有匹配的课程编号。')
            result={'cards':cards[args.offset:args.offset+args.limit],'count':len(cards),'offset':args.offset,'limit':args.limit,'detail':bool(args.id)}
        else:
            path=Path(args.spec).resolve();spec=read(path);cfg=load_config(args.config)
            if args.command=='validate':
                result=validate(spec,path.parent,cfg)
                print(json.dumps({'ok':result['valid'],'data':result},ensure_ascii=False));return 0 if result['valid'] else 2
            if args.command=='native-capabilities':
                from video_edit.technique_native import capabilities
                result=capabilities(spec,path.parent,cfg)
                print(json.dumps({'ok':result['valid'],'data':result},ensure_ascii=False));return 0 if result['valid'] else 2
            output=Path(args.output).resolve()
            if args.command=='export-jianying':
                from video_edit.technique_native import export_native
                result=export_native(spec,path.parent,cfg,output,name=args.name,allow_derived=args.allow_derived)
            elif args.command=='compile':
                if output.exists():raise EditError('OUTPUT_EXISTS','技巧输出目录已存在，请使用新目录。')
                result=compile_spec(spec,path.parent,cfg,output)
            else:result=render(spec,path.parent,cfg,output)
        print(json.dumps({'ok':True,'data':result},ensure_ascii=False));return 0
    except EditError as exc:
        print(json.dumps({'ok':False,'code':exc.code,'message':str(exc),'details':exc.details},ensure_ascii=False));return 2
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({'ok':False,'code':'TECHNIQUE_FAILED','message':str(exc)},ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())

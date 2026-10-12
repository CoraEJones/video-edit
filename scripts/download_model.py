"""Run from setup.ps1 without PowerShell native argument quote ambiguity."""
import sys,argparse,json,time,os
from pathlib import Path
os.environ.setdefault('HF_HUB_ETAG_TIMEOUT','15')
os.environ.setdefault('HF_HUB_DOWNLOAD_TIMEOUT','60')
from huggingface_hub import snapshot_download

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('cache_dir');parser.add_argument('--result',required=True)
    args=parser.parse_args();required=['model.bin','config.json','tokenizer.json','vocabulary.txt']
    for attempt in range(3):
        try:
            model=snapshot_download('Systran/faster-whisper-small',cache_dir=args.cache_dir,
                revision='536b0662742c02347bc0e980a01041f333bce120',allow_patterns=required,max_workers=2)
            if not all((Path(model)/f).is_file() and (Path(model)/f).stat().st_size>0 for f in required):raise RuntimeError('模型缺少必要文件')
            Path(args.result).write_text(json.dumps({'ok':True,'model':model},ensure_ascii=False),encoding='utf-8')
            print('本地语音模型已就绪。');break
        except Exception as exc:
            print(f'模型下载尝试 {attempt+1}/3 未完成：{exc}',file=sys.stderr)
            if attempt==2:
                Path(args.result).write_text(json.dumps({'ok':False,'code':'MODEL_DOWNLOAD_FAILED','message':str(exc)},ensure_ascii=False),encoding='utf-8')
                sys.exit(2)
            time.sleep(2)

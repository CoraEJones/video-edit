"""Stdlib-first probe; works before packages are installed."""
import argparse, importlib, importlib.metadata, json, struct, sys
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--python-only',action='store_true')
parser.add_argument('--config')
args=parser.parse_args()
sys.stdout.reconfigure(encoding='utf-8')
usable=sys.version_info >= (3,11) and struct.calcsize('P')==8
try:
    import tkinter,venv
except ImportError:usable=False
result={'usable':usable,'python':sys.executable,'version':sys.version.split()[0]}
if not args.python_only:
    missing=[];dependency_errors={}
    for name in ('numpy','PIL','fontTools','faster_whisper','pyJianYingDraft'):
        try:
            module=importlib.import_module(name)
            if name=='pyJianYingDraft' and (importlib.metadata.version(name)!='0.3.0' or not hasattr(module,'JianyingDraftCryptoCodec')):missing.append(name)
        except Exception as exc:
            missing.append(name);dependency_errors[name]=f'{type(exc).__name__}: {exc}'
    from video_edit.common import load_config,model_path
    cfg=load_config(args.config);model=model_path(cfg)
    if model and not all((Path(model)/f).is_file() and (Path(model)/f).stat().st_size>0 for f in ('model.bin','config.json','tokenizer.json','vocabulary.txt')):model=None
    result.update(missing_dependencies=missing,dependency_errors=dependency_errors,model=model,ffmpeg=cfg['ffmpeg'],ffprobe=cfg['ffprobe'],font_ready=Path(cfg['font_path']).is_file())
print(json.dumps(result,ensure_ascii=False))

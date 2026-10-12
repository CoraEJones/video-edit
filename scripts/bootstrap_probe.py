"""Stdlib-first, mode-aware probe used before optional packages are installed."""
import argparse, json, struct, sys
from pathlib import Path
parser=argparse.ArgumentParser()
parser.add_argument('--python-only',action='store_true')
parser.add_argument('--config')
args=parser.parse_args()
sys.stdout.reconfigure(encoding='utf-8')
usable=sys.version_info >= (3,11) and struct.calcsize('P')==8
try:
    import venv
except ImportError:usable=False
result={'usable':usable,'python':sys.executable,'version':sys.version.split()[0]}
if not args.python_only:
    from video_edit.common import load_config,model_path
    from video_edit.environment import dependency_state,selection
    cfg=load_config(args.config);model=model_path(cfg)
    modules,missing,errors=dependency_state(cfg)
    if model and not all((Path(model)/f).is_file() and (Path(model)/f).stat().st_size>0 for f in ('model.bin','config.json','tokenizer.json','vocabulary.txt')):model=None
    result.update(selection(cfg), missing_dependencies=missing,dependency_errors=errors,
        optional_dependencies={k:v for k,v in modules.items() if k not in missing},
        model=model,transcription_required=bool(cfg.get('transcription_required',False)),
        ffmpeg=cfg.get('ffmpeg'),ffprobe=cfg.get('ffprobe'),font_ready=bool(cfg.get('font_path')) and Path(cfg['font_path']).is_file())
print(json.dumps(result,ensure_ascii=False))

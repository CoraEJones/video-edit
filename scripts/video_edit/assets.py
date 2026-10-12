"""Prepare immutable source references, or portable copies for editable projects."""
from pathlib import Path
from .common import EditError, probe, progress, run, sha256, shutil, write


def prepare_assets(plan, rows, folder, cfg, copy_originals=True):
    from PIL import Image, ImageOps
    folder = Path(folder)
    lookup = {r['id']: r for r in rows}
    selected = {s['id'] for s in plan['shots']
                if not str(s.get('purpose', '')).startswith('panels_')}
    selected.update(s['id'] for s in plan.get('panels', []))
    selected.update(s['id'] for s in plan.get('visual_layers', []))
    for directory in ('audio', 'graphics') + (('originals', 'video') if copy_originals else ()):
        (folder / 'assets' / directory).mkdir(parents=True, exist_ok=True)
    assets, manifest = {}, []
    for ident in sorted(selected):
        row = lookup[ident]
        source = Path(row['absolute_path']).resolve()
        before = source.stat()
        progress(('打包完整原片：' if copy_originals else '核对原片引用：') + source.name)
        dest = folder / 'assets/originals' / f'{ident}_{source.name}' if copy_originals else source
        if copy_originals:
            shutil.copy2(source, dest)
        digest = sha256(dest)
        after = source.stat()
        if (after.st_size, after.st_mtime_ns) != (before.st_size, before.st_mtime_ns) or (
                copy_originals and sha256(source) != digest):
            raise EditError('SOURCE_CHANGED', '准备期间原素材发生变化，已停止生成。', {'path': str(source)})
        record = {'source': str(source), 'sha256': digest, 'size': before.st_size,
                  'mtime_ns': before.st_mtime_ns, 'copied': copy_originals}
        if copy_originals:
            record['relative'] = dest.relative_to(folder).as_posix()
        manifest.append(record)
        audio = None
        if row.get('kind') == 'image':
            with Image.open(dest) as original:
                img = ImageOps.exif_transpose(original)
                metadata = {'width': img.width, 'height': img.height, 'rotation': 0}
        else:
            metadata = probe(dest, cfg)
            if row.get('has_audio', metadata.get('has_audio', False)):
                if copy_originals:
                    audio = folder / 'assets/audio' / f'{ident}_完整原声.wav'
                    run([cfg['ffmpeg'], '-v', 'error', '-i', dest, '-vn', '-ac', '2', '-ar',
                         '48000', '-c:a', 'pcm_s16le', '-y', audio], timeout=1800)
                else:
                    # Only approved retained intervals are decoded by prepare_audio.
                    # A muted movie needs neither a full WAV nor a source movie copy.
                    audio = dest
        assets[ident] = {'video': str(dest), 'audio': str(audio) if audio else None,
                         'original': str(dest), 'duration': row['duration'],
                         'kind': row.get('kind', 'video'), 'source_metadata': metadata,
                         'original_sha256': digest, 'video_reencoded': False,
                         'normalization': ('原片逐字节复制并直接用于剪映；分辨率、编码、帧率与 HDR 数据保留'
                                           if copy_originals else '直接读取原片；不复制、不预转码、不修改原片')}
    Image.new('RGB', (plan['width'], plan['height']), 'black').save(folder / 'assets/graphics/black.png')
    write(folder / 'source-manifest.json', manifest)
    return assets


def verify_referenced_sources(folder):
    """Detect changes during export, while leaving every source untouched."""
    from .common import read
    for record in read(Path(folder) / 'source-manifest.json'):
        source = Path(record['source'])
        if not source.is_file():
            raise EditError('SOURCE_CHANGED', '渲染期间原素材被移动或删除。', {'path': str(source)})
        stat = source.stat()
        if (stat.st_size, stat.st_mtime_ns) != (record['size'], record['mtime_ns']) or sha256(source) != record['sha256']:
            raise EditError('SOURCE_CHANGED', '渲染期间原素材发生变化，成片未通过验收。', {'path': str(source)})

"""Standalone final MP4 delivery. Jianying and its draft library are optional."""
from __future__ import annotations
import copy
from pathlib import Path
from . import __version__
from .common import EditError, read, write, safe_name, progress, shutil, resolve_path
from .plan import validate, inventory_for
from .assets import prepare_assets


def export(plan_path, out, cfg, name=None):
    plan_path = resolve_path(plan_path)
    plan = read(plan_path)
    from .intake import require_delivery_request
    require_delivery_request(plan.get('request', {}), out, 'mp4', cfg)
    plan['name'] = safe_name(name or plan.get('name', '我的回忆'))
    report = validate(plan, plan_path, cfg)
    if not report['valid']:
        raise EditError('INVALID_PLAN', '剪辑计划检查未通过。', report)
    folder = resolve_path(out) / plan['name']
    if folder.exists():
        raise EditError('OUTPUT_EXISTS', '输出已存在，请使用新的作品名称或输出位置。', {'path': str(folder)})
    # Never reuse an earlier package, even when another exporter created it.
    folder.mkdir(parents=True, exist_ok=False)
    rows = inventory_for(plan, plan_path)
    local = copy.deepcopy(plan)
    local.pop('inventory', None)
    local['inventory_path'] = 'inventory.json'
    write(folder / 'edit-plan.json', local)
    write(folder / 'inventory.json', rows)
    write(folder / 'validation.json', report)
    try:
        assets = prepare_assets(local, rows, folder, cfg, copy_originals=False)
        write(folder / 'prepared-assets.json', assets)
        from .typography import prepare
        from .sound import prepare_audio
        from .preview import write_srt
        from .stream_render import render
        prepare(local, assets, folder, cfg)
        progress('准备经过审核的原声、配乐与字幕…')
        sound = prepare_audio(local, assets, folder, cfg)
        write(folder / 'edit-plan.json', local)
        srt = write_srt(local, folder)
        story = Path(plan_path).parent / 'story.txt'
        if story.is_file():
            shutil.copy2(story, folder / 'story.txt')
        movie = folder / (local['name'] + '.mp4')
        # Final delivery always uses the plan's full canvas and frame rate.
        # preview_mode=draft is deliberately irrelevant to final MP4 export.
        quality = render(local, assets, folder, cfg, movie)
        audit = {'tool_version': __version__, 'delivery': 'mp4', 'output_path': str(folder),
                 'movie': str(movie), 'preview': str(movie), 'duration_seconds': local['duration'],
                 'editable_project': False, 'requires_jianying': False,
                 'originals_copied_in_full': False, 'original_video_modified': False,
                 'source_hashes_verified': True, 'video_reencoding_before_edit': False,
                 'srt': srt, 'quality': quality, 'source_quality': report.get('quality'),
                 'warnings': report['warnings'] + sound.get('warnings', []),
                 'voices': sound.get('voices', []),
                 'visual_review_completed': False, 'listening_review_completed': False,
                 'note': '完整解码和结构检查已通过；仍需实际审看、试听最终成片。'}
        write(folder / 'verification.json', audit)
        (folder / '成片说明.txt').write_text(
            f'成片：{movie.name}\n规格：{local["width"]} × {local["height"]}，{local["fps"]} 帧/秒。\n'
            '无需安装剪映即可播放 MP4。字幕和标题已合成进画面；本交付不含剪映可编辑工程。\n'
            '原片只读引用，没有复制整套原素材、预压缩或修改原片。渲染使用未压缩图像流，仅最后一次编码 MP4。\n'
            '合成、画幅和帧率转换会改变像素，最终 H.264 MP4 仍是有损 SDR；HDR 输入会色调映射为 SDR。\n'
            'MP4 可单独分享；任务记录用于继续让助手修改，仍依赖原素材与所选音乐的原路径。\n'
            '修改时保留原素材及素材路径，重新从原片导出新名称，不要反复压制已生成 MP4。\n'
            '技术检查不能代替实际审看和试听。\n', encoding='utf-8-sig')
        return audit
    except BaseException as exc:
        write(folder / 'failure.json', {'message': str(exc), 'code': getattr(exc, 'code', 'EXPORT_FAILED'),
                                      'partial_output': str(folder), 'final_delivery_complete': False})
        raise

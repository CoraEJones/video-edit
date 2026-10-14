"""Generate a clean synthetic pixel QA example; no user media or Jianying.

The output is a technical fixture, not generated Chinese calligraphy or an
aesthetic pass. Every output path is new and the source artwork stays intact.
"""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw
from visual_qa import inspect_title, write_previews


def generate(output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    background = Image.new('RGB', (320, 180), '#1D4347')
    ImageDraw.Draw(background).rectangle((230, 70, 295, 165), fill='#B7D4C6')
    background.save(root / 'background.png')
    artwork = Image.new('RGBA', (160, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(artwork)
    draw.line([(15, 60), (40, 15), (65, 55), (90, 20), (140, 45)], fill='#F5D89E', width=10)
    artwork.save(root / 'synthetic-strokes.png')
    request = {
        'schema_version': 'title-visual-qa/1',
        'canvas': {'width_px': 320, 'height_px': 180},
        'title_image': 'synthetic-strokes.png',
        'transform': {'x_px': 30, 'y_px': 40, 'width_px': 160, 'height_px': 80},
        'rgb_transfer': 'srgb',
        'safe_margin_px': {'left': 12, 'top': 12, 'right': 12, 'bottom': 12},
        'frames': [{'path': 'background.png', 'source_time_s': 0, 'label': 'synthetic technical fixture',
                    'protected_rectangles': [{'id': 'synthetic-subject', 'reason': 'Explicit test rectangle, not automatic detection',
                                              'x_px': 230, 'y_px': 70, 'width_px': 66, 'height_px': 96}]}]
    }
    (root / 'request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
    report = inspect_title(request, base_dir=root)
    report['preview_files'] = write_previews(request, root / 'previews', base_dir=root)
    (root / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'example': str(root), 'report': str(root / 'report.json'), 'human_visual_review_status': 'pending'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False))


if __name__ == '__main__':
    main()

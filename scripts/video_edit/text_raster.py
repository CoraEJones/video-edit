"""Rasterize local font glyphs to a bounded, transparent text asset.

Glow is an alpha blur with constant text RGB, not a proprietary preset. The
requested font size and glyph geometry are preserved; oversized text is rejected
instead of silently shrunk, wrapped, stretched, or cropped.
"""
import math
from numbers import Real
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageDraw, ImageFilter, ImageFont


MAX_CANVAS_PIXELS = 16_777_216
MAX_TEXT_LENGTH = 500


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def _number(value, name, low, high):
    if (isinstance(value, bool) or not isinstance(value, Real)
            or not math.isfinite(value) or not low <= value <= high):
        raise ValueError(f'{name} must be finite and in {low}..{high}')
    return float(value)


def _rgb(value, name):
    if not isinstance(value, str) or re.fullmatch(r'#[0-9a-fA-F]{6}', value) is None:
        raise ValueError(f'{name} must be #RRGGBB')
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def render_text(canvas_size, text, font_path, font_size_px, color='#FFFFFF',
                stroke_px=0, stroke_color='#000000', glow_radius_px=0,
                glow_opacity=0.6):
    """Return centered multiline text as a full-canvas PIL RGBA image.

    Sizes and stroke widths use pixels; glow radius uses Pillow GaussianBlur
    pixels. Text is at most 500 Unicode code points. Newlines are supported and
    lines share a centered alignment with 20% of font size as extra line spacing.
    A three-radius transparent margin protects the glow from canvas clipping.
    No output file is written and no font substitution or external lookup occurs.
    """
    if not isinstance(canvas_size, (tuple, list)) or len(canvas_size) != 2:
        raise ValueError('canvas_size must be (width, height)')
    width = _integer(canvas_size[0], 'canvas width', 1, 16_384)
    height = _integer(canvas_size[1], 'canvas height', 1, 16_384)
    if width * height > MAX_CANVAS_PIXELS:
        raise ValueError(f'canvas exceeds {MAX_CANVAS_PIXELS} pixels')
    font_size_px = _integer(font_size_px, 'font_size_px', 1, 2048)
    stroke_px = _integer(stroke_px, 'stroke_px', 0, 128)
    radius = _number(glow_radius_px, 'glow_radius_px', 0, 256)
    opacity = _number(glow_opacity, 'glow_opacity', 0, 1)
    foreground = _rgb(color, 'color')
    outline = _rgb(stroke_color, 'stroke_color')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_LENGTH:
        raise ValueError(f'text must contain visible text and be <= {MAX_TEXT_LENGTH} characters')
    text = text.replace('\r\n', '\n')
    if any(unicodedata.category(char) == 'Cc' and char != '\n' for char in text):
        raise ValueError('text may contain newlines, but no other control characters')
    path = Path(font_path)
    if not path.is_file():
        raise FileNotFoundError(f'font file does not exist: {path}')
    font = ImageFont.truetype(str(path), font_size_px)
    spacing = max(1, round(font_size_px * 0.2))
    measure = ImageDraw.Draw(Image.new('L', (1, 1)))
    left, top, right, bottom = measure.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing, align='center', stroke_width=stroke_px)
    ink_width, ink_height = right - left, bottom - top
    margin = math.ceil(3 * radius) + 1 if radius and opacity else 1
    if (ink_width <= 0 or ink_height <= 0
            or ink_width + 2 * margin > width or ink_height + 2 * margin > height):
        raise ValueError('text, stroke, and glow must fit canvas at the requested font size')
    xy = ((width - ink_width) / 2 - left, (height - ink_height) / 2 - top)
    glyphs = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(glyphs).multiline_text(
        xy, text, font=font, spacing=spacing, align='center',
        fill=foreground + (255,), stroke_width=stroke_px, stroke_fill=outline + (255,))
    if glyphs.getchannel('A').getbbox() is None:
        raise ValueError('font produced no visible glyphs for text')
    if not radius or not opacity:
        return glyphs
    core = Image.new('L', (width, height), 0)
    ImageDraw.Draw(core).multiline_text(xy, text, font=font, spacing=spacing, align='center', fill=255)
    blurred_alpha = core.filter(ImageFilter.GaussianBlur(radius)).point(
        [round(alpha * opacity) for alpha in range(256)])
    glow = Image.new('RGBA', (width, height), foreground + (0,))
    glow.putalpha(blurred_alpha)
    return Image.alpha_composite(glow, glyphs)

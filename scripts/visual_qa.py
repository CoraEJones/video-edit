"""Pixel evidence for transparent title artwork on actual video backgrounds.

This is an advisory inspection tool, not an aesthetic grader. Coordinates are
canvas pixels, origin at the top left, x right, y down. Frame times are seconds
in the source video, not frame indices or timeline times. Ordinary SDR images
are interpreted as sRGB for luminance calculations; this module performs no
camera colour-space inference, HDR conversion, face detection or segmentation.
Set rgb_transfer="bt709" only when BOTH background and artwork have explicitly
been rendered into BT.709 RGB; the default is "srgb". No conversion is implied.

Request/API example::

    inspect_title({
        "schema_version": "title-visual-qa/1",
        "canvas": {"width_px": 1280, "height_px": 720},
        "title_image": "/absolute/title.png",
        "transform": {
            "x_px": 100, "y_px": 80, "width_px": 600, "height_px": 200,
            "rotation_deg": 0, "opacity": 1.0
        },
        "roi": {"x_px": 80, "y_px": 60, "width_px": 660, "height_px": 240},
        "safe_margin_px": {"left": 48, "top": 36, "right": 48, "bottom": 36},
        "palette_colors": 4,
        "frames": [{
            "path": "/absolute/background-at-source-12.5.png",
            "source_time_s": 12.5,
            "label": "middle",
            "protected_rectangles": [{
                "id": "hand-action", "reason": "manually reviewed hand action",
                "x_px": 800, "y_px": 200, "width_px": 200, "height_px": 250
            }]
        }]
    })

The x/y coordinates refer to the top left of the resized *unrotated* artwork.
Positive rotation is clockwise about that rectangle's centre. Width and height
are explicit pixel sizes, not normalized native-Jianying scale or position.
Per-frame transform/ROI/protected_rectangles can override the shared values.
Opacity is applied to the actual alpha. Optional readability_mask is a grayscale
image in original artwork coordinates: white evaluates the title, black omits
decorations from readability statistics; all artwork still counts for occlusion.

CLI::

    python visual_qa.py --request request.json --output NEW-report.json \
        --preview-dir NEW-preview-directory

Every output must be new. Original artwork/backgrounds are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw


SCHEMA = "title-visual-qa/1"
COORDINATES = {
    "position_unit": "canvas_pixel",
    "origin": "top_left",
    "x_direction": "right",
    "y_direction": "down",
    "rotation_unit": "degrees_clockwise_about_unrotated_rectangle_center",
    "source_time_unit": "source_seconds",
}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _integer(value: Any, name: str, minimum: Optional[int] = None) -> int:
    number = _finite(value, name)
    if number != int(number) or (minimum is not None and number < minimum):
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(number)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path(value: Any, base: Optional[Path]) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute() and base is not None:
        path = base / path
    return path.resolve(strict=True)


def _rect(value: Mapping[str, Any], size: Tuple[int, int], name: str) -> Tuple[int, int, int, int]:
    x = _integer(value["x_px"], f"{name}.x_px", 0)
    y = _integer(value["y_px"], f"{name}.y_px", 0)
    width = _integer(value["width_px"], f"{name}.width_px", 1)
    height = _integer(value["height_px"], f"{name}.height_px", 1)
    if x + width > size[0] or y + height > size[1]:
        raise ValueError(f"{name} must be wholly inside the canvas")
    return x, y, x + width, y + height


def _rect_dict(rect: Tuple[int, int, int, int]) -> Dict[str, int]:
    x0, y0, x1, y1 = rect
    return {"x_px": x0, "y_px": y0, "width_px": x1 - x0, "height_px": y1 - y0}


def _bbox(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _luminance(rgb: np.ndarray, transfer: str = "srgb") -> np.ndarray:
    srgb = np.asarray(rgb, dtype=np.float64) / 255.0
    if transfer == "srgb":
        linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    elif transfer == "bt709":
        linear = np.where(srgb < 0.081, srgb / 4.5, ((srgb + 0.099) / 1.099) ** (1 / 0.45))
    else:
        raise ValueError("rgb_transfer must be srgb or bt709; unknown/HDR material needs upstream normalization")
    return linear[..., 0] * 0.2126 + linear[..., 1] * 0.7152 + linear[..., 2] * 0.0722


def _stats(values: np.ndarray) -> Optional[Dict[str, float]]:
    if not values.size:
        return None
    return {
        "min": float(values.min()),
        "p05": float(np.percentile(values, 5)),
        "p10": float(np.percentile(values, 10)),
        "median": float(np.median(values)),
        "p90": float(np.percentile(values, 90)),
        "max": float(values.max()),
    }


def _morph(mask: np.ndarray, *, erode: bool, radius: int) -> np.ndarray:
    result = mask.astype(bool, copy=True)
    for _ in range(radius):
        padded = np.pad(result, 1, mode="constant", constant_values=False)
        neighbours = [padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
                      for dy in range(3) for dx in range(3)]
        result = np.logical_and.reduce(neighbours) if erode else np.logical_or.reduce(neighbours)
    return result


def _quantized_palette(sample: Image.Image, colors: int, transfer: str = "srgb") -> List[Dict[str, Any]]:
    colors = _integer(colors, "palette_colors", 2)
    if colors > 4:
        raise ValueError("palette_colors must be between 2 and 4")
    quantized = sample.quantize(colors=colors, method=0, dither=0)
    color_table = quantized.getpalette()
    result = []
    for count, index in sorted(quantized.getcolors() or [], reverse=True):
        rgb = tuple(color_table[index * 3:index * 3 + 3])
        result.append({
            "rgb": list(rgb),
            "hex": "#%02X%02X%02X" % rgb,
            "area_fraction": count / (sample.width * sample.height),
            "relative_luminance": float(_luminance(np.array(rgb), transfer)),
        })
    return result


def palette(image: Image.Image, rect: Tuple[int, int, int, int], colors: int = 4, transfer: str = "srgb") -> List[Dict[str, Any]]:
    """Deterministic area-weighted median-cut palette from the explicit ROI."""
    sample = image.convert("RGB").crop(rect)
    sample.thumbnail((320, 320), Image.Resampling.NEAREST if hasattr(Image, "Resampling") else Image.NEAREST)
    return _quantized_palette(sample, colors, transfer)


def _palette_under_mask(image: Image.Image, mask: np.ndarray, colors: int, transfer: str = "srgb") -> List[Dict[str, Any]]:
    """Use only background pixels underneath actual metric alpha, not a poster box."""
    pixels = np.asarray(image.convert("RGB"))[mask]
    if not pixels.size:
        return []
    # Deterministic raster-order subsampling preserves the scope of the mask.
    if len(pixels) > 102400:
        pixels = pixels[np.linspace(0, len(pixels) - 1, 102400, dtype=np.int64)]
    sample = Image.fromarray(pixels.reshape(1, len(pixels), 3), "RGB")
    return _quantized_palette(sample, colors, transfer)


def _transform_layer(image: Image.Image, transform: Mapping[str, Any], canvas: Tuple[int, int]) -> Tuple[Image.Image, Dict[str, Any]]:
    x = _finite(transform["x_px"], "transform.x_px")
    y = _finite(transform["y_px"], "transform.y_px")
    width = _integer(transform["width_px"], "transform.width_px", 1)
    height = _integer(transform["height_px"], "transform.height_px", 1)
    angle = _finite(transform.get("rotation_deg", 0), "transform.rotation_deg")
    opacity = _finite(transform.get("opacity", 1.0), "transform.opacity")
    if not 0 <= opacity <= 1:
        raise ValueError("transform.opacity must be between 0 and 1")
    resampling = Image.Resampling if hasattr(Image, "Resampling") else Image
    # Pillow RGBA resizing uses premultiplied alpha, avoiding a straight-RGB fringe.
    resized = image.convert("RGBA").resize((width, height), resample=resampling.LANCZOS)
    rotated = resized.rotate(-angle, resample=resampling.BICUBIC, expand=True) if angle % 360 else resized
    paste_x = int(round(x + width / 2 - rotated.width / 2))
    paste_y = int(round(y + height / 2 - rotated.height / 2))
    rgba = np.array(rotated, dtype=np.uint8)
    rgba[..., 3] = np.rint(rgba[..., 3].astype(np.float64) * opacity).astype(np.uint8)
    rotated = Image.fromarray(rgba, "RGBA")
    layer = Image.new("RGBA", canvas, (0, 0, 0, 0))
    # No paste mask: the source alpha is copied exactly, not multiplied twice.
    layer.paste(rotated, (paste_x, paste_y))
    total_alpha = float(rgba[..., 3].sum(dtype=np.float64))
    visible_alpha = float(np.asarray(layer)[..., 3].sum(dtype=np.float64))
    return layer, {
        "unrotated_rect_px": {"x_px": x, "y_px": y, "width_px": width, "height_px": height},
        "rotation_deg": angle,
        "opacity": opacity,
        "rasterized_placement_px": {"x_px": paste_x, "y_px": paste_y, "width_px": rotated.width, "height_px": rotated.height},
        "visible_alpha_mass_fraction": visible_alpha / total_alpha if total_alpha else 1.0,
        "off_canvas_alpha_mass_fraction": max(0.0, 1 - visible_alpha / total_alpha) if total_alpha else 0.0,
        "rounding": "expanded rectangle top-left rounded to nearest integer canvas pixel",
    }


def _source_alpha(artwork: Image.Image) -> Dict[str, Any]:
    alpha = np.asarray(artwork)[..., 3].astype(np.float64) / 255.0
    border = np.concatenate((alpha[0], alpha[-1], alpha[1:-1, 0], alpha[1:-1, -1]))
    bbox = _bbox(alpha >= 0.05)
    return {
        "has_alpha_channel": True,
        "transparent_fraction": float(np.mean(alpha == 0)),
        "semi_transparent_fraction": float(np.mean((alpha > 0) & (alpha < 1))),
        "opaque_fraction": float(np.mean(alpha == 1)),
        "alpha_bbox_px": _rect_dict(bbox) if bbox else None,
        "border_visible_fraction_at_alpha_0_05": float(np.mean(border >= 0.05)),
        "corner_alpha_max": float(max(alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1])),
        "edge_interpretation": "Nonzero borders can indicate cropped strokes or a retained rectangle; inspect pixels. White fringes cannot be inferred without knowing intended ink colours.",
    }


def _frame_analysis(background: Image.Image, layer: Image.Image, metric_mask: Optional[Image.Image],
                    safe: Mapping[str, Any], protected: List[Mapping[str, Any]],
                    alpha_threshold: float, core_threshold: float, feature_px: int,
                    palette_colors: int = 4, transfer: str = "srgb") -> Tuple[Dict[str, Any], Image.Image]:
    bg = np.asarray(background.convert("RGB"), dtype=np.uint8)
    rgba = np.asarray(layer, dtype=np.uint8)
    alpha = rgba[..., 3].astype(np.float64) / 255.0
    composite = Image.alpha_composite(background.convert("RGBA"), layer).convert("RGB")
    output_luma = _luminance(np.asarray(composite), transfer)
    background_luma = _luminance(bg, transfer)
    foreground_luma = _luminance(rgba[..., :3], transfer)
    # This measures the actual composited pixel, including fading/partial alpha.
    contrast = (np.maximum(output_luma, background_luma) + 0.05) / (np.minimum(output_luma, background_luma) + 0.05)
    opaque_contrast = (np.maximum(foreground_luma, background_luma) + 0.05) / (np.minimum(foreground_luma, background_luma) + 0.05)
    metric_alpha = alpha
    if metric_mask is not None:
        metric_alpha = alpha * (np.asarray(metric_mask)[..., 3].astype(np.float64) / 255.0)
    visible = metric_alpha >= alpha_threshold
    core = metric_alpha >= core_threshold
    radius = (feature_px - 1) // 2
    opened = _morph(_morph(core, erode=True, radius=radius), erode=False, radius=radius)
    narrow = core & ~opened
    visible_bbox = _bbox(alpha >= alpha_threshold)
    width, height = background.size
    margins = {name: _finite(safe.get(name, 0), f"safe_margin_px.{name}") for name in ("left", "top", "right", "bottom")}
    if any(value < 0 for value in margins.values()) or margins["left"] + margins["right"] >= width or margins["top"] + margins["bottom"] >= height:
        raise ValueError("safe margins must be nonnegative and leave a positive canvas area")
    actual_margins = None if visible_bbox is None else {
        "left": visible_bbox[0], "top": visible_bbox[1],
        "right": width - visible_bbox[2], "bottom": height - visible_bbox[3],
    }
    violations = [] if actual_margins is None else [side for side in margins if actual_margins[side] < margins[side]]
    overlaps = []
    for index, item in enumerate(protected):
        rect = _rect(item, background.size, f"protected_rectangles[{index}]")
        x0, y0, x1, y1 = rect
        crop = alpha[y0:y1, x0:x1]
        overlap_mass = float(crop.sum())
        overlaps.append({
            "id": str(item.get("id", index)), "reason": str(item.get("reason", "manually protected region")),
            "rectangle_px": _rect_dict(rect),
            "visible_overlap_pixels": int(np.count_nonzero(crop >= alpha_threshold)),
            "core_overlap_pixels": int(np.count_nonzero(crop >= core_threshold)),
            "alpha_weighted_region_coverage_fraction": overlap_mass / crop.size,
            "fraction_of_visible_artwork_alpha_in_region": overlap_mass / float(alpha.sum()) if alpha.sum() else 0.0,
        })
    # Pixel gradient is a texture warning, not a semantic background classifier.
    gx = np.zeros_like(background_luma)
    gy = np.zeros_like(background_luma)
    gx[:, 1:] = np.abs(background_luma[:, 1:] - background_luma[:, :-1])
    gy[1:, :] = np.abs(background_luma[1:, :] - background_luma[:-1, :])
    gradient = np.maximum(gx, gy)
    flags = []
    if not visible.any():
        flags.append("NO_VISIBLE_READABILITY_PIXELS_AT_THIS_OPACITY")
    if violations:
        flags.append("ARTWORK_INSIDE_REQUESTED_SAFE_MARGIN")
    if any(item["visible_overlap_pixels"] for item in overlaps):
        flags.append("ARTWORK_OVERLAPS_MANUALLY_PROTECTED_REGION")
    if visible.any() and np.mean(contrast[visible] < 1.5) > 0.1:
        flags.append("LOCAL_COMPOSITE_CONTRAST_BELOW_1_5_ON_MORE_THAN_10_PERCENT")
    if narrow.any() and np.percentile(contrast[narrow], 10) < 3:
        flags.append("NARROW_FEATURE_LOW_LOCAL_CONTRAST")
    return {
        "visible_artwork_bbox_px": _rect_dict(visible_bbox) if visible_bbox else None,
        "readability_scope": "explicit_grayscale_mask_times_actual_alpha" if metric_mask is not None else "all_visible_artwork_including_decorations",
        "readability_pixels": int(visible.sum()),
        "core_pixels": int(core.sum()),
        "contrast_actual_composite_to_background": _stats(contrast[visible]),
        "contrast_opaque_ink_to_background": _stats(opaque_contrast[visible]),
        "fraction_below_contrast_1_5": float(np.mean(contrast[visible] < 1.5)) if visible.any() else None,
        "fraction_below_contrast_3": float(np.mean(contrast[visible] < 3)) if visible.any() else None,
        "narrow_feature_check": {
            "opening_kernel_width_px": feature_px,
            "core_pixels_removed_by_square_opening": int(narrow.sum()),
            "fraction_of_core_removed": float(narrow.sum() / core.sum()) if core.any() else None,
            "contrast_actual_composite": _stats(contrast[narrow]),
            "interpretation": "Pixels removed by a square opening indicate fine strokes, serifs, tips or isolated details at this resolution; this is not a measured font stroke width or OCR test.",
        },
        "background_under_readability_pixels": {
            "palette": _palette_under_mask(background, visible, palette_colors, transfer),
            "palette_scope": "background_pixels_under_actual_metric_alpha_at_visible_threshold",
            "luminance": _stats(background_luma[visible]),
            "luminance_standard_deviation": float(np.std(background_luma[visible])) if visible.any() else None,
            "maximum_axis_adjacent_pixel_luminance_difference": _stats(gradient[visible]),
        },
        "safe_margin": {"requested_px": margins, "actual_alpha_bbox_distance_px": actual_margins, "violated_sides": violations},
        "protected_regions": overlaps,
        "flags_for_human_review": flags,
        "human_visual_review": {"status": "pending", "semantic_subject_safety": "manual_rectangles_only", "aesthetic_acceptance": None},
    }, composite


def _load(request: Mapping[str, Any], base: Optional[Path]) -> Tuple[Tuple[int, int], Path, Image.Image, Optional[Image.Image]]:
    if request.get("schema_version") != SCHEMA:
        raise ValueError(f"schema_version must be {SCHEMA}")
    canvas = request["canvas"]
    size = (_integer(canvas["width_px"], "canvas.width_px", 1), _integer(canvas["height_px"], "canvas.height_px", 1))
    title_path = _path(request["title_image"], base)
    with Image.open(title_path) as source:
        if "A" not in source.getbands() and "transparency" not in source.info:
            raise ValueError("title_image must contain a real alpha/transparency channel")
        artwork = source.convert("RGBA")
        artwork.info.update(source.info)
    mask = None
    if request.get("readability_mask"):
        with Image.open(_path(request["readability_mask"], base)) as source:
            if source.mode not in ("1", "L", "I", "I;16"):
                raise ValueError("readability_mask must be an explicit grayscale image")
            if source.size != artwork.size:
                raise ValueError("readability_mask must have the original title dimensions")
            white = Image.new("RGBA", source.size, (255, 255, 255, 0))
            white.putalpha(source.convert("L"))
            mask = white
    if not request.get("frames"):
        raise ValueError("at least one actual background frame is required")
    return size, title_path, artwork, mask


def inspect_title(request: Mapping[str, Any], *, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return JSON-ready evidence without writing or modifying any files."""
    base = Path(base_dir).resolve() if base_dir is not None else None
    size, title_path, artwork, readability_mask = _load(request, base)
    transfer = request.get("rgb_transfer", "srgb")
    _luminance(np.array([0, 0, 0]), transfer)  # Validate even when every frame is transparent.
    thresholds = request.get("thresholds", {})
    alpha_threshold = _finite(thresholds.get("visible_alpha", 32 / 255), "thresholds.visible_alpha")
    core_threshold = _finite(thresholds.get("core_alpha", 0.5), "thresholds.core_alpha")
    if not 0 < alpha_threshold <= core_threshold <= 1:
        raise ValueError("alpha thresholds must satisfy 0 < visible_alpha <= core_alpha <= 1")
    feature_px = _integer(thresholds.get("minimum_feature_px", 3), "thresholds.minimum_feature_px", 3)
    if feature_px % 2 == 0 or feature_px > 15:
        raise ValueError("minimum_feature_px must be an odd integer between 3 and 15")
    frames = []
    for index, item in enumerate(request["frames"]):
        path = _path(item["path"], base)
        source_time = _finite(item["source_time_s"], f"frames[{index}].source_time_s")
        if source_time < 0:
            raise ValueError("source frame times must be >= 0 seconds")
        with Image.open(path) as source:
            if source.size != size:
                raise ValueError(f"background {path.name} dimensions {source.size} differ from canvas {size}; render an explicit background first")
            background = source.convert("RGB")
            has_icc = bool(source.info.get("icc_profile"))
        transform = dict(request.get("transform", {}))
        transform.update(item.get("transform", {}))
        layer, placement = _transform_layer(artwork, transform, size)
        metric_mask = _transform_layer(readability_mask, {**transform, "opacity": 1.0}, size)[0] if readability_mask is not None else None
        actual_alpha_bbox = _bbox(np.asarray(layer)[..., 3] / 255 >= alpha_threshold)
        supplied_roi = item.get("roi", request.get("roi"))
        roi = _rect(supplied_roi, size, f"frames[{index}].roi") if supplied_roi is not None else actual_alpha_bbox
        metrics, _ = _frame_analysis(background, layer, metric_mask,
                                     request.get("safe_margin_px", {}),
                                     item.get("protected_rectangles", request.get("protected_rectangles", [])),
                                     alpha_threshold, core_threshold, feature_px,
                                     request.get("palette_colors", 4), transfer)
        if placement["off_canvas_alpha_mass_fraction"] > 1e-6:
            metrics["flags_for_human_review"].append("ARTWORK_ALPHA_CLIPPED_OUTSIDE_CANVAS")
        if has_icc:
            metrics["flags_for_human_review"].append("BACKGROUND_EMBEDDED_ICC_PRESENT_NO_CONVERSION_PERFORMED")
        frames.append({
            "index": index, "label": str(item.get("label", "")),
            "source_time_s": source_time, "background_path": str(path), "background_sha256": _sha256(path),
            "transform": placement, "palette_roi_px": _rect_dict(roi) if roi else None,
            "palette_roi_scope": "explicit_per_frame_or_shared_roi" if supplied_roi is not None else "current_frame_actual_visible_artwork_alpha_bbox",
            "background_palette": palette(background, roi, request.get("palette_colors", 4), transfer) if roi else [],
            **metrics,
        })
    return {
        "schema_version": SCHEMA,
        "coordinates": COORDINATES,
        "rgb_transfer": {"declaration": transfer, "source": "explicit_request_or_documented_srgb_default", "color_conversion_performed": False, "assumes_background_and_artwork_share_this_encoding": True},
        "canvas": {"width_px": size[0], "height_px": size[1]},
        "title_image": str(title_path), "title_sha256": _sha256(title_path),
        "original_title_size_px": {"width_px": artwork.width, "height_px": artwork.height},
        "source_alpha": _source_alpha(artwork),
        "thresholds": {"visible_alpha": alpha_threshold, "core_alpha": core_threshold, "minimum_feature_px": feature_px},
        "frames": frames,
        "summary": {
            "frame_count": len(frames),
            "flags_for_human_review": sorted({flag for frame in frames for flag in frame["flags_for_human_review"]}),
            "contains_automatic_face_or_subject_detection": False,
            "aesthetic_grade": None,
            "human_visual_review_status": "pending",
            "limits": [
                "Numeric contrast and morphology are advisory; they do not validate Chinese characters, calligraphy quality, artistic hierarchy or taste.",
                "Only supplied frames and manually protected rectangles were inspected; motion between frames remains unverified.",
                "Artwork may include decorative accessories; provide readability_mask to isolate letterforms while retaining complete occlusion checks.",
                "All RGB is interpreted using the reported transfer declaration. Background and artwork must share that encoding; unknown/HDR/Log material requires explicit upstream conversion.",
                "A source alpha border can reveal possible clipping or retained backgrounds; halo colour requires visual comparison on actual frames.",
            ],
        },
    }


def write_previews(request: Mapping[str, Any], directory: Path, *, base_dir: Optional[Path] = None) -> List[str]:
    """Write new composite/audit PNGs into a directory that must not exist."""
    base = Path(base_dir).resolve() if base_dir is not None else None
    size, _, artwork, _ = _load(request, base)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    written = []
    for index, item in enumerate(request["frames"]):
        with Image.open(_path(item["path"], base)) as source:
            if source.size != size:
                raise ValueError("background dimensions differ from canvas")
            background = source.convert("RGBA")
        transform = dict(request.get("transform", {}))
        transform.update(item.get("transform", {}))
        layer, _ = _transform_layer(artwork, transform, size)
        composite = Image.alpha_composite(background, layer).convert("RGB")
        composite_path = directory / f"frame-{index + 1:03d}-composite.png"
        composite.save(composite_path)
        audit = composite.copy()
        draw = ImageDraw.Draw(audit)
        visible_alpha = _finite(request.get("thresholds", {}).get("visible_alpha", 32 / 255), "thresholds.visible_alpha")
        alpha_bbox = _bbox(np.asarray(layer)[..., 3] / 255 >= visible_alpha)
        if alpha_bbox is not None:
            draw.rectangle((alpha_bbox[0], alpha_bbox[1], alpha_bbox[2] - 1, alpha_bbox[3] - 1), outline="#FFFF00", width=1)
        supplied_roi = item.get("roi", request.get("roi"))
        roi = _rect(supplied_roi, size, "roi") if supplied_roi is not None else alpha_bbox
        if roi is not None:
            draw.rectangle((roi[0], roi[1], roi[2] - 1, roi[3] - 1), outline="#00FFFF", width=1)
        for rectangle in item.get("protected_rectangles", request.get("protected_rectangles", [])):
            rect = _rect(rectangle, size, "protected_rectangle")
            draw.rectangle((rect[0], rect[1], rect[2] - 1, rect[3] - 1), outline="#FF3366", width=2)
        audit_path = directory / f"frame-{index + 1:03d}-audit.png"
        audit.save(audit_path)
        written.extend((str(composite_path.resolve()), str(audit_path.resolve())))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new JSON file; existing files are refused")
    parser.add_argument("--preview-dir", type=Path, help="new directory for actual composite and annotated audit PNGs")
    args = parser.parse_args()
    if args.output.exists() or (args.preview_dir is not None and args.preview_dir.exists()):
        parser.error("all output paths must be new; no original or previous result will be overwritten")
    with args.request.open("r", encoding="utf-8-sig") as stream:
        request = json.load(stream)
    report = inspect_title(request, base_dir=args.request.parent)
    if args.preview_dir is not None:
        report["preview_files"] = write_previews(request, args.preview_dir, base_dir=args.request.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"report": str(args.output.resolve()), **report["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

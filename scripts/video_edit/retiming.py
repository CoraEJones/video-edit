"""Explicit continuous speed model, independent of proprietary editor presets.

Each knot is exactly ``{'time': output_seconds, 'speed': source_seconds_per_
output_second}``. Speed is piecewise linear in *output time*. Integrating it
gives the source offset consumed by a clip; the inverse is analytic quadratic
math, not a list of constant-speed cuts. Times are local to a trimmed clip:
add source_in outside these helpers when seeking an original asset.

This model does not assert Jianying's unknown interpolation or axis domain.
It maps timestamps only; frame blending/optical flow and audio retiming are
separate, explicitly selected rendering policies.
"""

from collections.abc import Mapping, Sequence
import math
from numbers import Real


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite number')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'{name} must be a finite number')
    return result


def _knots(knots):
    if (not isinstance(knots, Sequence) or isinstance(knots, (str, bytes))
            or len(knots) < 2):
        raise ValueError('curve requires at least two ordered knots')
    result = []
    for index, knot in enumerate(knots):
        if not isinstance(knot, Mapping) or set(knot) != {'time', 'speed'}:
            raise ValueError('each knot must contain exactly time and speed')
        time = _number(knot['time'], f'knots[{index}].time')
        speed = _number(knot['speed'], f'knots[{index}].speed')
        if time < 0 or (result and time <= result[-1]['time']):
            raise ValueError('knot output times must be nonnegative and strictly increasing')
        if not .1 <= speed <= 10:
            raise ValueError('knot speed must be within 0.1..10')
        result.append({'time': time, 'speed': speed})
    if result[0]['time'] != 0:
        raise ValueError('curve must start at output time zero')
    return result


def validate_curve(knots, duration, fps):
    """Return copied numeric knots, or raise ValueError.

    The first/last output times must equal 0/duration. The duration endpoint
    must lie on the output frame grid. Interior knots can be subframe: their
    continuously interpolated speed is evaluated at each actual frame time.
    """
    rows = _knots(knots)
    duration = _number(duration, 'duration')
    fps = _number(fps, 'fps')
    if duration <= 0 or fps <= 0:
        raise ValueError('duration and fps must be positive')
    if not math.isclose(rows[-1]['time'], duration, rel_tol=0, abs_tol=1e-9):
        raise ValueError('last knot must equal output duration')
    frames = duration * fps
    if (not math.isfinite(frames) or round(frames) < 1
            or not math.isclose(frames, round(frames), rel_tol=0, abs_tol=1e-7)):
        raise ValueError('output duration endpoint must be frame aligned')
    rows[-1]['time'] = duration
    list(_segments(rows))
    return rows


def _segments(rows):
    spans = []
    for left, right in zip(rows, rows[1:]):
        start = math.fsum(spans)
        width = right['time'] - left['time']
        span = width * (left['speed'] + right['speed']) / 2
        slope = (right['speed']-left['speed'])/width
        if not math.isfinite(span) or span <= 0 or not math.isfinite(slope):
            raise ValueError('curve source span must be finite and positive')
        spans.append(span)
        end = math.fsum(spans)
        if not math.isfinite(end) or end <= start:
            raise ValueError('curve exceeds numeric source-time precision')
        yield left['time'], width, left['speed'], slope, start, end


def source_span(knots):
    """Source seconds consumed over the full output duration (not output seconds)."""
    segments = list(_segments(_knots(knots)))
    return segments[-1][-1]


def _bounded(value, maximum, name):
    value = _number(value, name)
    # Only floating-point roundoff at a boundary is clamped, not real overrun.
    tolerance = 32 * math.ulp(maximum)
    if value < -tolerance or value > maximum + tolerance:
        raise ValueError(f'{name} must be within 0..{maximum:g}')
    return min(maximum, max(0., value))


def source_time(knots, output_time):
    """Map local output seconds to local source seconds by integrating speed."""
    rows = _knots(knots)
    value = _bounded(output_time, rows[-1]['time'], 'output_time')
    segments = list(_segments(rows))
    if value == rows[-1]['time']:
        return segments[-1][-1]
    for time, width, speed, slope, start, end in segments:
        if value <= time + width:
            local = value - time
            return start + local * (speed + .5 * slope * local)
    raise ValueError('output time outside curve')


def output_time(knots, source_seconds):
    """Invert local source seconds to output seconds without iterative search."""
    rows = _knots(knots)
    segments = list(_segments(rows))
    value = _bounded(source_seconds, segments[-1][-1], 'source_seconds')
    if value == segments[-1][-1]:
        return rows[-1]['time']
    for time, width, speed, slope, start, end in segments:
        if value <= end:
            distance = max(0., value - start)
            # Rationalized root avoids cancellation for tiny slopes/distances,
            # including negative slopes; speed is always strictly positive.
            root = math.sqrt(max(0., speed * speed + 2 * slope * distance))
            local = 2 * distance / (speed + root)
            return time + min(width, max(0., local))
    raise ValueError('source time outside curve')


def _literal(value):
    return format(value, '.17g')


def setpts_expression(knots, variable='PTS*TB'):
    """Return an FFmpeg setpts expression mapping source timestamps to output.

    ``variable`` evaluates to local source seconds (default PTS*TB). The
    returned value is output PTS ticks, hence the final division by TB. Trim
    and zero the input timestamps before using this expression, and quote it
    as a filter expression so its commas are preserved. Set a sufficiently
    fine input time base (for example settb=AVTB) before setpts. This helper
    does not add fps conversion or choose a frame-interpolation algorithm.

    FFmpeg cannot raise Python errors for out-of-domain frames: the generated
    expression clamps to the two endpoints. Python mapping helpers instead
    reject genuine overruns. Within the domain both mappings are identical.
    """
    if not isinstance(variable, str) or not variable.strip():
        raise ValueError('variable must be a nonempty FFmpeg seconds expression')
    rows = _knots(knots)
    segments = list(_segments(rows))
    value = f'({variable})'
    expression = _literal(rows[-1]['time'])
    for time, width, speed, slope, start, end in reversed(segments):
        distance = f'({value}-{_literal(start)})'
        if slope == 0:
            local = f'({distance}/{_literal(speed)})'
        else:
            local = (f'(2*{distance}/({_literal(speed)}+'
                     f'sqrt(max(0,{_literal(speed*speed)}+'
                     f'({_literal(2*slope)})*{distance}))))')
        segment = f'({_literal(time)}+{local})'
        expression = f'if(lt({value},{_literal(end)}),{segment},{expression})'
    return f'(if(lte({value},0),0,{expression}))/TB'

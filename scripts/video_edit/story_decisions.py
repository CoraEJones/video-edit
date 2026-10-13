"""Validate editorial sidecars and suggest existing cuts; never edit/render a plan."""
import argparse
import json
import math
from pathlib import Path

from .retiming import output_time, source_span, validate_curve


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def number(value, label, minimum=0, positive=False):
    require(type(value) in (int, float) and math.isfinite(value), label + ': finite number required')
    require(value > minimum if positive else value >= minimum, label + ': out of range')
    return value


def fields(obj, required, label):
    require(isinstance(obj, dict), label + ': object required')
    require(set(obj) == set(required.split()), label + ': missing/unknown fields')


def label(value):
    require(isinstance(value, str) and bool(value.strip()), 'nonempty string required')
    return value


def items(value):
    require(isinstance(value, list), 'array required')
    return value


def interval(obj, limit):
    a = number(obj['source_start'], 'source_start')
    b = number(obj['source_end'], 'source_end')
    require(a < b <= limit, 'invalid source interval')
    return a, b


def _aligned(value, fps, name):
    frames = number(value * fps, 'derived frame position')
    require(abs(frames - round(frames)) < 1e-7, name + ': not frame aligned')


def _duration(shot):
    if 'speed' in shot:
        return (shot['source_end'] - shot['source_start']) / shot['speed']
    return shot['output_duration']


def _same_time(left, right):
    return math.isclose(left, right, rel_tol=0, abs_tol=1e-8)


def _validate_mapping(shot, fps):
    """Use output-time speed integrals or explicit PTS samples, never frame indices."""
    mapping = shot['time_map']
    require(isinstance(mapping, dict), 'time_map: object required')
    duration = number(shot['output_duration'], 'output_duration', positive=True)
    kind = mapping.get('kind')
    if kind == 'constant':
        fields(mapping, 'kind speed', 'constant time_map')
        speed = number(mapping['speed'], 'speed', positive=True)
        require(.25 <= speed <= 4, 'speed outside bridge range .25..4')
        span = number(duration * speed, 'derived source span', positive=True)
    elif kind == 'speed_curve':
        fields(mapping, 'kind knots', 'speed_curve time_map')
        try:
            curve = validate_curve(mapping['knots'], duration, fps)
            span = source_span(curve)
        except (ValueError, TypeError, OverflowError) as exc:
            raise Invalid('speed_curve: ' + str(exc)) from exc
    elif kind == 'pts':
        fields(mapping, 'kind points review_ref', 'PTS time_map')
        label(mapping['review_ref'])
        points = items(mapping['points'])
        require(len(points) >= 2, 'PTS mapping requires start/end samples')
        last_source = last_output = -1
        for p in points:
            fields(p, 'source_time output_time', 'PTS point')
            source = number(p['source_time'], 'PTS source_time')
            output = number(p['output_time'], 'PTS output_time')
            require(source > last_source and output > last_output, 'PTS pairs must strictly increase')
            require(shot['source_start'] <= source <= shot['source_end'], 'PTS source point outside shot')
            require(output <= duration, 'PTS output point outside shot')
            _aligned(output, fps, 'PTS output time')
            last_source, last_output = source, output
        require(_same_time(points[0]['source_time'], shot['source_start'])
                and points[0]['output_time'] == 0
                and _same_time(points[-1]['source_time'], shot['source_end'])
                and _same_time(points[-1]['output_time'], duration), 'PTS mapping endpoints mismatch')
        return duration
    else:
        raise Invalid('unsupported time_map kind; freeze/reverse require a reviewed derived asset')
    require(_same_time(span, shot['source_end'] - shot['source_start']), 'time_map source span mismatch')
    return duration


def _map_source(shot, source):
    if 'speed' in shot:
        return (source - shot['source_start']) / shot['speed']
    mapping = shot['time_map']
    if mapping['kind'] == 'constant':
        return (source - shot['source_start']) / mapping['speed']
    if mapping['kind'] == 'speed_curve':
        return output_time(mapping['knots'], source - shot['source_start'])
    # PTS pairs are exact declared render/frame samples. Interpolating between
    # them would invent frames for VFR, freezes or nonlinear proprietary curves.
    for point in mapping['points']:
        if _same_time(point['source_time'], source):
            return point['output_time']
    raise Invalid('candidate source_time lacks an exact PTS mapping sample')


def validate(data):
    """Raise Invalid on malformed/inconsistent evidence; return indexed validated data.

    Evidence declarations are not proof of their factual truth. No files are inspected.
    """
    fields(data, 'schema_version fps assets events shots protected candidates music max_beat_distance', 'root')
    require(data['schema_version'] in ('story-decisions/1', 'story-decisions/2'), 'unsupported schema')
    fps = number(data['fps'], 'fps', positive=True)
    require(fps in (24, 25, 30, 50, 60), 'fps not supported by bridge plan')
    number(data['max_beat_distance'], 'max_beat_distance')
    assets = {}
    for a in items(data['assets']):
        fields(a, 'id duration', 'asset')
        aid = label(a['id'])
        require(aid not in assets, 'duplicate asset')
        assets[aid] = number(a['duration'], 'asset duration', positive=True)
    events = {}
    for e in items(data['events']):
        fields(e, 'id evidence', 'event')
        eid = label(e['id'])
        require(eid not in events, 'duplicate event')
        require(bool(items(e['evidence'])), 'event requires evidence')
        for ev in e['evidence']:
            fields(ev, 'asset_id source_start source_end review_ref', 'evidence')
            require(ev['asset_id'] in assets, 'unknown evidence asset')
            interval(ev, assets[ev['asset_id']])
            label(ev['review_ref'])
        events[eid] = e
    shots = {}
    for s in items(data['shots']):
        shot_fields = 'shot_id asset_id event_id reaction_to_event_id source_start source_end timeline_start '
        shot_fields += 'speed' if data['schema_version'] == 'story-decisions/1' else 'output_duration time_map'
        fields(s, shot_fields, 'shot')
        sid = label(s['shot_id'])
        require(sid not in shots, 'duplicate shot')
        require(s['asset_id'] in assets and s['event_id'] in events, 'unknown shot asset/event')
        a, b = interval(s, assets[s['asset_id']])
        if data['schema_version'] == 'story-decisions/1':
            speed = number(s['speed'], 'speed', positive=True)
            require(.25 <= speed <= 4, 'speed outside bridge range .25..4')
            duration = number((b-a)/speed, 'derived duration', positive=True)
        else:
            duration = _validate_mapping(s, fps)
        start = number(s['timeline_start'], 'timeline_start')
        number(start + duration, 'derived shot end')
        for t in (start, duration):
            _aligned(t, fps, 'shot timeline')
        evidence = events[s['event_id']]['evidence']
        require(any(ev['asset_id'] == s['asset_id'] and ev['source_start'] <= a and ev['source_end'] >= b for ev in evidence), 'shot outside reviewed event evidence')
        r = s['reaction_to_event_id']
        require(r is None or (r in events and r == s['event_id']), 'reaction event mismatch')
        shots[sid] = s
    ordered = sorted(shots.values(), key=lambda s: s['timeline_start'])
    for x, y in zip(ordered, ordered[1:]):
        require(x['timeline_start'] + _duration(x) <= y['timeline_start']+1e-9, 'shot overlap')
    protections = []
    for p in items(data['protected']):
        fields(p, 'asset_id source_start source_end kind review_ref', 'protected')
        require(p['asset_id'] in assets, 'unknown protected asset')
        interval(p, assets[p['asset_id']])
        require(p['kind'] in ('semantic', 'action', 'reaction'), 'unknown protected kind')
        label(p['review_ref'])
        protections.append(p)
    ids = set()
    for c in items(data['candidates']):
        fields(c, 'id shot_id source_time dramatic_beat_id review_ref', 'candidate')
        cid = label(c['id'])
        require(cid not in ids, 'duplicate candidate')
        ids.add(cid)
        require(c['shot_id'] in shots, 'unknown candidate shot')
        s = shots[c['shot_id']]
        t = number(c['source_time'], 'candidate source time')
        require(s['source_start'] < t < s['source_end'], 'candidate must be interior to shot')
        number(_map_source(s, t), 'mapped candidate output time')
        require(c['dramatic_beat_id'] in events and c['dramatic_beat_id'] == s['event_id'], 'dramatic beat must reference shot event, not music beat')
        label(c['review_ref'])
    m = data['music']
    if m is not None:
        fields(m, 'asset_id source_start source_end timeline_start listened_ranges beats', 'music')
        require(m['asset_id'] in assets, 'unknown music asset')
        a, b = interval(m, assets[m['asset_id']])
        number(m['timeline_start'], 'music timeline_start')
        number(m['timeline_start'] + (b-a), 'derived music end')
        for r in items(m['listened_ranges']):
            fields(r, 'source_start source_end review_ref', 'listened range')
            ra, rb = interval(r, assets[m['asset_id']])
            require(a <= ra < rb <= b, 'listened range outside music selection')
            label(r['review_ref'])
        last = -1
        for beat in items(m['beats']):
            number(beat, 'music beat')
            require(a <= beat <= b and beat > last, 'music beats must be sorted unique and in range')
            require(any(r['source_start'] <= beat <= r['source_end'] for r in m['listened_ranges']), 'music beat not covered by listening evidence')
            last = beat
    return shots, protections


def suggest(data):
    """Rank only exact frame-aligned declared candidates. Never snap into protection."""
    shots, protections = validate(data)
    m = data['music']
    beats = [] if m is None else [m['timeline_start']+(b-m['source_start']) for b in m['beats']]
    rejected, legal = [], []
    for c in data['candidates']:
        s = shots[c['shot_id']]
        source = c['source_time']
        timeline = number(s['timeline_start'] + _map_source(s, source), 'mapped candidate timeline')
        reasons = []
        if abs(timeline*data['fps']-round(timeline*data['fps'])) >= 1e-7:
            reasons.append('NOT_FRAME_ALIGNED')
        if any(p['asset_id'] == s['asset_id'] and p['source_start'] < source < p['source_end'] for p in protections):
            reasons.append('PROTECTED_INTERIOR')
        distance = min((abs(timeline-b) for b in beats), default=None)
        if distance is not None and distance > data['max_beat_distance']+1e-9:
            reasons.append('OUTSIDE_BEAT_WINDOW')
        if reasons:
            rejected.append({'id': c['id'], 'reasons': reasons})
        else:
            legal.append({'id': c['id'], 'shot_id': c['shot_id'], 'source_time': source,
                          'timeline_time': timeline, 'distance_to_music_beat': distance})
    legal.sort(key=lambda c: (c['distance_to_music_beat'] or 0, c['timeline_time'], c['id']))
    return {'selected': legal[0] if legal else None, 'legal': legal, 'rejected': rejected,
            'status': 'REQUIRES_EDITORIAL_REVIEW' if legal else 'NO_LEGAL_CANDIDATE',
            'applied_to_plan': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'suggest'])
    parser.add_argument('sidecar', type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.sidecar.read_text(encoding='utf-8-sig'))
        if args.command == 'validate':
            validate(data)
            result = {'status': 'STRUCTURE_VALID_NOT_FACT_VERIFIED', 'applied_to_plan': False}
        else:
            result = suggest(data)
        print(json.dumps({'ok': True, 'code': result['status'], 'data': result}, ensure_ascii=False))
        return 0
    except (Invalid, ValueError, OSError, TypeError, KeyError, OverflowError) as exc:
        print(json.dumps({'ok': False, 'code': 'INVALID_SIDECAR', 'message': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

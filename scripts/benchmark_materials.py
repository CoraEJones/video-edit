"""Real corpus transport/cache/handoff benchmark; does not invent editorial truth."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import platform
import sys
import time

from video_edit.common import read, write, load_config
from video_edit.intake import require_confirmed_request
from video_edit import analysis, material_memory, __version__


def run(request_path, job, cfg):
    request = read(request_path)
    require_confirmed_request(request, cfg)
    job = Path(job).resolve()
    if (job / 'inventory.json').exists():
        raise ValueError('Use a new benchmark job for a meaningful cold-cache run.')
    observations = []
    original_run = analysis.run
    try:
        for stage, reuse in (('cold', False), ('warm', True)):
            calls = []
            def counted_run(args, *a, **kw):
                calls.append(str(args[0]))
                return original_run(args, *a, **kw)
            analysis.run = counted_run
            start = time.perf_counter()
            output = analysis.analyze(request['media_dir'], job, request, cfg,
                                      transcribe=False, reuse=reuse)
            rows = read(output['inventory'])
            observations.append({'stage': stage, 'seconds': round(time.perf_counter() - start, 3),
                'reported_count': output['media_count'], 'persisted_count': len(rows),
                'ready_count': output['ready_count'], 'external_decode_extract_calls': len(calls),
                'frame_count': sum(len(r.get('frames', [])) for r in rows)})
    finally:
        analysis.run = original_run
    start = time.perf_counter()
    state = material_memory.initialize(job, batch_size=12)
    with material_memory.connect(job) as db:
        ids = [r['id'] for r in db.execute('SELECT id FROM batches ORDER BY id')]
    packet_lengths = [len(json.dumps(material_memory.packet(job, ident), ensure_ascii=False,
                                    separators=(',', ':'))) for ident in ids]
    result = {'schema_version': 'material-benchmark-1.0', 'skill_version': __version__,
        'python': platform.python_version(), 'system': platform.system(),
        'scope': 'Actual corpus decode/extraction, cache and bounded handoffs. No ASR, semantic selection, listening or aesthetic score.',
        'runs': observations, 'total_source_seconds': round(sum(r.get('duration', 0) for r in rows), 3),
        'total_source_bytes': sum(Path(r['absolute_path']).stat().st_size for r in rows),
        'memory': {'seconds': round(time.perf_counter() - start, 3), 'batch_count': len(ids),
                   'max_packet_chars': max(packet_lengths, default=0),
                   'packet_budget_chars': 14000, 'inventory_json_bytes': (job / 'inventory.json').stat().st_size,
                   'all_assets_still_require_semantic_review': not state['all_reviewed']},
        'checks': {'report_matches_inventory': all(r['reported_count'] == r['persisted_count'] for r in observations),
                   'warm_visual_cache_has_zero_extraction_calls': observations[1]['external_decode_extract_calls'] == 0,
                   'all_packets_within_budget': all(n <= 14000 for n in packet_lengths)},
        'editorial_benchmark': {'status': 'pending_human_annotations_and_blind_review',
            'metrics': ['key_moment_recall', 'candidate_precision', 'story_comprehension',
                        'rhythm', 'dialogue_integrity', 'color_continuity', 'sound_quality',
                        'human_revision_minutes']}}
    write(job / 'benchmark-result.json', result)
    return result


def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--job', required=True)
    parser.add_argument('--config')
    a = parser.parse_args()
    result = run(a.request, a.job, load_config(a.config))
    print(json.dumps(result, ensure_ascii=False))
    if not all(result['checks'].values()): sys.exit(2)


if __name__ == '__main__': main()

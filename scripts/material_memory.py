"""Bounded handoff CLI. Read-only packet/search operations never review media."""
import argparse
import json
import sys
from video_edit.common import EditError
from video_edit import material_memory as memory


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Disk material memory and scoped worker handoffs')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'status', 'claim', 'packet', 'ingest', 'query', 'compile', 'reopen'):
        p = sub.add_parser(name)
        p.add_argument('--job', required=True)
        if name == 'init': p.add_argument('--batch-size', type=int, default=12)
        if name in ('claim', 'ingest'): p.add_argument('--worker', required=True)
        if name == 'claim': p.add_argument('--lease-seconds', type=int, default=1800)
        if name in ('packet', 'ingest', 'reopen'): p.add_argument('--batch', required=True)
        if name == 'packet': p.add_argument('--worker')
        if name == 'ingest': p.add_argument('--result', required=True)
        if name == 'query':
            p.add_argument('--query', default='')
            p.add_argument('--limit', type=int, default=8)
        if name in ('packet', 'query'): p.add_argument('--max-chars', type=int, default=14000 if name == 'packet' else 12000)
    a = parser.parse_args()
    try:
        if a.command == 'init': result = memory.initialize(a.job, a.batch_size)
        elif a.command == 'status': result = memory.status(a.job)
        elif a.command == 'claim': result = memory.claim(a.job, a.worker, a.lease_seconds)
        elif a.command == 'reopen': result = memory.reopen(a.job, a.batch)
        elif a.command == 'packet': result = memory.packet(a.job, a.batch, a.worker, a.max_chars)
        elif a.command == 'ingest': result = memory.ingest(a.job, a.batch, a.worker, a.result)
        elif a.command == 'query': result = memory.query(a.job, a.query, a.limit, a.max_chars)
        else: result = memory.compile_analysis(a.job)
        print(json.dumps({'ok': True, 'data': result}, ensure_ascii=False))
    except EditError as exc:
        print(json.dumps({'ok': False, 'code': exc.code, 'message': str(exc), 'data': exc.details}, ensure_ascii=False))
        sys.exit(2)


if __name__ == '__main__': main()

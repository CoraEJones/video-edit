"""Disk-backed material index and leased, bounded handoffs; no model or auto-review.

Inventory and complete observations stay on disk. Workers receive assigned IDs,
small navigation packets and paths to records, never the entire material library.
"""
from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import shutil
import time

from .common import EditError, read, write

SCHEMA = 'material-memory-1.0'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


@contextmanager
def connect(job):
    path = Path(job).resolve() / 'memory/index.sqlite3'
    if not path.is_file():
        raise EditError('MEMORY_NOT_INITIALIZED', '先运行 material_memory.py init。')
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def fingerprint(row):
    # Include analysis signatures so new evidence invalidates old observations.
    return digest({k: row.get(k) for k in ('id', 'absolute_path', 'fingerprint',
                    'analysis_signature', 'visual_signature', 'transcription_signature',
                    'cache', 'analysis_cache', 'frames', 'transcript', 'status')})


def initialize(job, batch_size=12):
    job = Path(job).resolve()
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 50:
        raise EditError('MEMORY_BATCH_SIZE', '每批数量应为 1–50，通常从 8–12 开始。')
    rows = read(job / 'inventory.json')
    if not isinstance(rows, list) or len({r['id'] for r in rows}) != len(rows):
        raise EditError('MEMORY_INVENTORY', '需要编号唯一的素材清单。')
    memory = job / 'memory'
    (memory / 'records').mkdir(parents=True, exist_ok=True)
    (memory / 'results').mkdir(exist_ok=True)
    (memory / 'submissions').mkdir(exist_ok=True)
    (memory / 'segments').mkdir(exist_ok=True)
    db = sqlite3.connect(memory / 'index.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    with db:
        db.executescript('''
          CREATE TABLE IF NOT EXISTS assets(
            id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, record_path TEXT NOT NULL,
            search_text TEXT NOT NULL, status TEXT NOT NULL, batch_id TEXT);
          CREATE TABLE IF NOT EXISTS batches(
            id TEXT PRIMARY KEY, asset_ids TEXT NOT NULL, status TEXT NOT NULL,
            worker TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
            result_path TEXT, updated REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS segments(
            id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, source_in REAL NOT NULL,
            source_out REAL NOT NULL, decision TEXT, search_text TEXT NOT NULL,
            record TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS segment_asset ON segments(asset_id);
        ''')
        ids = {r['id'] for r in rows}
        for old in db.execute('SELECT id FROM assets').fetchall():
            if old['id'] not in ids:
                db.execute('DELETE FROM segments WHERE asset_id=?', (old['id'],))
                db.execute('DELETE FROM assets WHERE id=?', (old['id'],))
        changed = set()
        for row in rows:
            ident = row['id']
            # IDs become filenames; inventory IDs must never escape the job.
            if not ident or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in ident):
                raise EditError('MEMORY_ASSET_ID', '素材编号只能包含字母、数字、下划线和连字符。')
            record = memory / 'records' / (ident + '.json')
            fp = fingerprint(row)
            previous = db.execute('SELECT fingerprint FROM assets WHERE id=?', (ident,)).fetchone()
            write(record, row)
            if not previous or previous['fingerprint'] != fp:
                changed.add(ident)
                db.execute('DELETE FROM segments WHERE asset_id=?', (ident,))
                text = ' '.join(str(row.get(k, '')) for k in ('filename', 'relative_path', 'description', 'tags'))
                text += ' ' + ' '.join(t.get('text', '') for t in row.get('transcript', []))
                state = 'pending' if row.get('status') == 'analyzed' else 'analysis_failed'
                db.execute('INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?,NULL)',
                           (ident, fp, str(record.relative_to(job)), text, state))
        # Invalidate an entire handoff if its membership or any input changed.
        for batch in db.execute('SELECT * FROM batches').fetchall():
            members = set(json.loads(batch['asset_ids']))
            if members & changed or not members <= ids:
                for ident in members & ids:
                    db.execute("UPDATE assets SET batch_id=NULL,status=CASE WHEN status='analysis_failed' THEN status ELSE 'pending' END WHERE id=?", (ident,))
                    db.execute('DELETE FROM segments WHERE asset_id=?', (ident,))
                db.execute('DELETE FROM batches WHERE id=?', (batch['id'],))
        unassigned = [r['id'] for r in rows if db.execute('SELECT status,batch_id FROM assets WHERE id=?', (r['id'],)).fetchone()['batch_id'] is None
                      and r.get('status') == 'analyzed']
        for offset in range(0, len(unassigned), batch_size):
            members = unassigned[offset:offset + batch_size]
            fps = [db.execute('SELECT fingerprint FROM assets WHERE id=?', (i,)).fetchone()[0] for i in members]
            ident = 'batch-' + digest([members, fps])[:14]
            db.execute('INSERT INTO batches VALUES(?,?,?,NULL,NULL,0,NULL,?)',
                       (ident, json.dumps(members), 'pending', time.time()))
            for asset_id in members:
                db.execute('UPDATE assets SET batch_id=? WHERE id=?', (ident, asset_id))
    db.close()
    # Rebuild navigation artifacts from the durable index after upgrades/restarts.
    with connect(job) as db:
        for record in db.execute('SELECT s.id,s.asset_id,s.record,a.batch_id FROM segments s JOIN assets a ON a.id=s.asset_id'):
            detail = memory / 'segments' / (digest(record['id']) + '.json')
            if not detail.is_file():
                write(detail, {'asset_id': record['asset_id'], 'segment': json.loads(record['record']),
                    'batch_id': record['batch_id'], 'meaning': 'Validated worker declaration, not independent viewing proof.'})
    write(memory / 'manifest.json', {'schema_version': SCHEMA, 'inventory_path': '../inventory.json',
          'asset_count': len(rows), 'batch_size': batch_size,
          'meaning': 'Navigation and declarations only; analysis success never means semantic review.'})
    return status(job)


def status(job):
    with connect(job) as db:
        assets = {r['status']: r['n'] for r in db.execute('SELECT status,count(*) n FROM assets GROUP BY status')}
        batches = {r['status']: r['n'] for r in db.execute('SELECT status,count(*) n FROM batches GROUP BY status')}
        segments = db.execute('SELECT count(*) FROM segments').fetchone()[0]
    return {'schema_version': SCHEMA, 'assets': assets, 'batches': batches,
            'segment_count': segments, 'all_reviewed': not any(k != 'reviewed' and n for k, n in assets.items()),
            'next_action': 'Claim a pending batch; inspect its actual evidence; ingest the bounded result.'}


def claim(job, worker, lease_seconds=1800):
    if not isinstance(worker, str) or not worker.strip() or not 1 <= lease_seconds <= 86400:
        raise EditError('MEMORY_LEASE', '需要工作者标识和 1–86400 秒租约。')
    with connect(job) as db:
        db.execute('BEGIN IMMEDIATE')
        now = time.time()
        row = db.execute("SELECT * FROM batches WHERE status='pending' OR (status='running' AND lease_until<?) ORDER BY id LIMIT 1", (now,)).fetchone()
        if not row:
            return {'claimed': False, 'reason': 'No pending or expired batches.'}
        db.execute("UPDATE batches SET status='running',worker=?,lease_until=?,attempts=attempts+1,updated=? WHERE id=?",
                   (worker, now + lease_seconds, now, row['id']))
    return {'claimed': True, 'batch_id': row['id'], 'worker': worker, 'lease_until': now + lease_seconds,
            'next_command': 'packet --job JOB --batch ' + row['id'] + ' --worker ' + worker}


def reopen(job, batch_id):
    """Explicit refinement retains old evidence on disk, suspends stale candidates."""
    with connect(job) as db:
        db.execute('BEGIN IMMEDIATE')
        batch = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
        if not batch:
            raise EditError('MEMORY_BATCH_UNKNOWN', '批次不存在。')
        if batch['status'] == 'running' and batch['lease_until'] > time.time():
            raise EditError('MEMORY_BATCH_RUNNING', '批次仍被工作者持有，不能抢占；先完成或等待租约失效。')
        for ident in json.loads(batch['asset_ids']):
            db.execute("UPDATE assets SET status='needs_review' WHERE id=?", (ident,))
            db.execute('DELETE FROM segments WHERE asset_id=?', (ident,))
        db.execute("UPDATE batches SET status='pending',worker=NULL,lease_until=NULL,updated=? WHERE id=?",
                   (time.time(), batch_id))
    return {'batch_id': batch_id, 'status': 'pending', 'previous_result_preserved': bool(batch['result_path']),
            'next_action': 'Claim again, read previous_result_path, preserve earlier provenance and add actual review.'}


def _bounded(result, max_chars):
    if not isinstance(max_chars, int) or max_chars < 1000:
        raise EditError('MEMORY_BUDGET', '上下文预算至少为 1000 字符。')
    payload = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
    if len(payload) > max_chars:
        raise EditError('MEMORY_PACKET_TOO_LARGE', '必要路径与编号已超预算，请缩小批次；不能静默漏掉分配素材。',
                        {'required_chars': len(payload), 'max_chars': max_chars})
    return result


def packet(job, batch_id, worker=None, max_chars=14000):
    job = Path(job).resolve()
    with connect(job) as db:
        batch = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
        if not batch:
            raise EditError('MEMORY_BATCH_UNKNOWN', '批次不存在。')
        if worker and (batch['worker'] != worker or batch['status'] != 'running' or batch['lease_until'] < time.time()):
            raise EditError('MEMORY_LEASE', '此工作者没有该批次的有效租约。')
        items = []
        for ident in json.loads(batch['asset_ids']):
            entry = db.execute('SELECT * FROM assets WHERE id=?', (ident,)).fetchone()
            row = read(job / entry['record_path'])
            items.append({'id': ident, 'input_fingerprint': entry['fingerprint'],
                'record_path': str(job / entry['record_path']), 'filename': row.get('filename'),
                'duration': row.get('duration'), 'kind': row.get('kind'),
                'contact_sheets': row.get('contact_sheets', [])[:2],
                'contact_sheets_truncated': len(row.get('contact_sheets', [])) > 2,
                'transcript_excerpt': [{k: t.get(k) for k in ('start', 'end', 'text', 'confidence_warning')}
                                       for t in row.get('transcript', [])[:2]],
                'transcript_truncated': len(row.get('transcript', [])) > 2})
    request = read(job / 'request.json') if (job / 'request.json').is_file() else {}
    fields = ('theme', 'context', 'must_keep', 'must_keep_ranges', 'audience', 'viewing_context', 'audio_policy')
    constraints = {k: request[k] for k in fields if k in request}
    result = {'schema_version': SCHEMA, 'batch_id': batch_id, 'worker': batch['worker'],
              'job': str(job), 'request_path': str(job / 'request.json'),
              'shared_facts_path': str(job / 'memory/facts.json'), 'constraints': constraints,
              'assets': items, 'result_path': str(job / 'memory/submissions' / (batch_id + '-attempt' + str(batch['attempts']) + '.json')),
              'previous_result_path': str(job / batch['result_path']) if batch['result_path'] else None,
              'instructions': 'Read assigned record paths on demand. Inspect actual frames/audio. Return assets with observations, interpretations, coverage, source-second segments and unknowns. Never claim unviewed or unheard evidence. Do not edit the inventory or final plan.'}
    # Drop excerpts first, while retaining every assignment and navigation path.
    if len(json.dumps(result, ensure_ascii=False)) > max_chars:
        for item in items:
            item['transcript_excerpt'] = []
            item['transcript_truncated'] = True
    return _bounded(result, max_chars)


def ingest(job, batch_id, worker, result_path):
    job = Path(job).resolve()
    canonical = job / 'memory/results' / (batch_id + '.json')
    if Path(result_path).resolve() == canonical:
        raise EditError('MEMORY_RESULT_PATH', '工作者应写submissions或独立结果文件，canonical结果由ingest管理。')
    result = read(result_path)
    with connect(job) as db:
        db.execute('BEGIN IMMEDIATE')
        batch = db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
        if not batch or batch['status'] != 'running' or batch['worker'] != worker or batch['lease_until'] < time.time():
            raise EditError('MEMORY_LEASE', '结果只能由持有效租约的工作者提交。')
        expected = set(json.loads(batch['asset_ids']))
        observed = result.get('assets', [])
        if not isinstance(observed, list) or any(not isinstance(a, dict) for a in observed):
            raise EditError('MEMORY_RESULT', 'assets 需要对象列表。')
        ids = [a.get('id') for a in observed]
        if len(ids) != len(set(ids)) or set(ids) != expected:
            raise EditError('MEMORY_RESULT_SCOPE', '结果必须恰好覆盖本批编号，不得重复、漏项或越权。')
        pending_segments = []
        known_segments = set()
        current_rows = {r['id']: r for r in read(job / 'inventory.json')}
        for asset in observed:
            entry = db.execute('SELECT * FROM assets WHERE id=?', (asset['id'],)).fetchone()
            row = current_rows.get(asset['id'])
            if not row or fingerprint(row) != entry['fingerprint'] or asset.get('input_fingerprint') != entry['fingerprint']:
                raise EditError('MEMORY_STALE_RESULT', '素材或分析输入已变化，请重新初始化并分配。')
            source = Path(row['absolute_path'])
            stat = source.stat() if source.is_file() else None
            fp = row.get('fingerprint', {})
            if not stat or (fp and (stat.st_size != fp.get('size') or stat.st_mtime_ns != fp.get('mtime_ns'))):
                raise EditError('MEMORY_STALE_SOURCE', '原素材在分析后改变，请重新分析。')
            asset['fingerprint'] = row.get('fingerprint', {})
            state = asset.get('status')
            if state not in ('reviewed', 'pending', 'blocked_visual', 'needs_review', 'failed', 'analysis_failed'):
                raise EditError('MEMORY_RESULT_STATUS', '审看状态无效。')
            coverage = asset.get('coverage', {})
            evidence = coverage.get('contact_sheets_viewed', [])
            if state == 'reviewed' and not (evidence or coverage.get('playback_ranges') or coverage.get('frame_times_viewed')):
                raise EditError('MEMORY_REVIEW_EVIDENCE', 'reviewed 必须记录实际查看范围。')
            for p in evidence:
                path = Path(p) if Path(p).is_absolute() else job / p
                if not path.is_file():
                    raise EditError('MEMORY_REVIEW_EVIDENCE', '联系表证据不存在。')
            for segment in asset.get('segments', []):
                ident = segment.get('segment_id')
                start, end = segment.get('source_in'), segment.get('source_out')
                if (not isinstance(ident, str) or not ident or ident in known_segments or
                    any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)) or
                    not 0 <= start < end <= row['duration'] + .002):
                    raise EditError('MEMORY_SEGMENT', '区间编号必须唯一，源时间必须有效。')
                known_segments.add(ident)
                existing = db.execute('SELECT asset_id FROM segments WHERE id=?', (ident,)).fetchone()
                if existing and existing['asset_id'] not in expected:
                    raise EditError('MEMORY_SEGMENT_CONFLICT', '区间编号已属于其他批次。')
                if state != 'reviewed' and segment.get('decision') in ('candidate', 'backup'):
                    raise EditError('MEMORY_UNREVIEWED_SELECTION', '未审素材不能升级为已核实候选。')
                for e in segment.get('evidence', []):
                    path = Path(e.get('path', ''))
                    path = path if path.is_absolute() else job / path
                    if not path.is_file():
                        raise EditError('MEMORY_REVIEW_EVIDENCE', '区间证据文件不存在。')
                    if 'time' in e and not (isinstance(e['time'], (int, float)) and not isinstance(e['time'], bool)
                            and math.isfinite(e['time']) and 0 <= e['time'] <= row['duration']):
                        raise EditError('MEMORY_REVIEW_EVIDENCE', '证据时码超出原素材。')
                text = json.dumps({k: segment.get(k) for k in ('observations', 'interpretations', 'story_roles', 'tags', 'reason', 'unknowns')}, ensure_ascii=False)
                pending_segments.append((ident, asset['id'], start, end, segment.get('decision', 'pending'), text,
                                         json.dumps(segment, ensure_ascii=False, allow_nan=False)))
        for ident in expected:
            db.execute('DELETE FROM segments WHERE asset_id=?', (ident,))
        from .review_evidence import validate_analysis
        errors = validate_analysis(result, [current_rows[i] for i in expected], job)
        if errors:
            raise EditError('MEMORY_REVIEW_INVALID', '交接证据或源时码不一致。', {'errors': errors})
        db.executemany('INSERT INTO segments VALUES(?,?,?,?,?,?,?)', pending_segments)
        for record in pending_segments:
            detail = job / 'memory/segments' / (digest(record[0]) + '.json')
            write(detail, {'asset_id': record[1], 'segment': json.loads(record[6]),
                           'batch_id': batch_id, 'meaning': 'Validated worker declaration, not independent viewing proof.'})
        saved = job / 'memory/results' / (batch_id + '.json')
        if saved.is_file():
            archive = job / 'memory/history' / batch_id
            archive.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, archive / (str(time.time_ns()) + '.json'))
        write(saved, result)
        for asset in observed:
            db.execute('UPDATE assets SET status=? WHERE id=?', (asset['status'], asset['id']))
        db.execute("UPDATE batches SET status='completed',result_path=?,lease_until=NULL,updated=? WHERE id=?",
                   (str(saved.relative_to(job)), time.time(), batch_id))
    return status(job)


def query(job, text='', limit=8, max_chars=12000):
    if not 1 <= limit <= 50:
        raise EditError('MEMORY_QUERY_LIMIT', '检索数量应为 1–50。')
    terms = str(text).casefold().split()[:10]
    with connect(job) as db:
        # SQL parameters keep footage text and queries strictly as data.
        where = ' OR '.join('lower(s.search_text || a.search_text) LIKE ?' for _ in terms) or '1'
        rows = db.execute("SELECT s.*,a.record_path FROM segments s JOIN assets a ON a.id=s.asset_id WHERE s.decision IN ('candidate','backup') AND (" + where + ') ORDER BY s.asset_id,s.source_in LIMIT ?',
                          [('%' + t.replace('%', '').replace('_', '') + '%') for t in terms] + [limit + 1]).fetchall()
    items = []
    result = {'query': text, 'candidates': items, 'more_available': len(rows) > limit,
              'note': 'Search returns worker declarations, not independently proven facts. Read source records and evidence on demand.'}
    for row in rows[:limit]:
        segment = json.loads(row['record'])
        summary = {k: segment.get(k) for k in ('segment_id', 'source_in', 'source_out', 'decision')}
        summary['observations'] = [str(v)[:300] for v in segment.get('observations', [])[:2]]
        summary['story_roles'] = segment.get('story_roles', [])[:3]
        summary['reason'] = str(segment.get('reason', ''))[:250]
        summary['evidence_count'] = len(segment.get('evidence', []))
        entry = {'asset_id': row['asset_id'], 'record_path': str(Path(job).resolve() / row['record_path']),
                 'detail_path': str(Path(job).resolve() / 'memory/segments' / (digest(row['id']) + '.json')),
                 'segment': summary}
        items.append(entry)
        if len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))) > max_chars:
            items.pop()
            result['more_available'] = True
            break
    if not items and terms:
        with connect(job) as db:
            where = ' OR '.join('lower(search_text) LIKE ?' for _ in terms)
            navigation = db.execute('SELECT id,record_path,status FROM assets WHERE ' + where + ' ORDER BY id LIMIT 3',
                                    [('%' + t.replace('%', '').replace('_', '') + '%') for t in terms]).fetchall()
        result['metadata_navigation'] = [{'asset_id': r['id'], 'status': r['status'],
            'record_path': str(Path(job).resolve() / r['record_path']),
            'meaning': 'Metadata match only; not a reviewed candidate.'} for r in navigation]
    return _bounded(result, max_chars)


def compile_analysis(job):
    job = Path(job).resolve()
    assets = []
    inventory = {r['id']: r for r in read(job / 'inventory.json')}
    with connect(job) as db:
        for batch in db.execute("SELECT result_path FROM batches WHERE status='completed' ORDER BY id"):
            for asset in read(job / batch['result_path'])['assets']:
                row = inventory.get(asset['id'])
                if not row or asset.get('input_fingerprint') != fingerprint(row):
                    raise EditError('MEMORY_STALE_RESULT', '完整清单已变化，请重新初始化失效批次后合并。')
                assets.append(asset)
        present = {a['id'] for a in assets}
        assets.extend({'id': r['id'], 'status': r['status'], 'segments': [], 'unknowns': ['Review incomplete.']}
                      for r in db.execute('SELECT id,status FROM assets ORDER BY id') if r['id'] not in present)
    facts = read(job / 'memory/facts.json') if (job / 'memory/facts.json').is_file() else []
    output = {'schema_version': 'material-analysis-1.0', 'inventory_path': 'inventory.json',
              'time_basis': 'source_seconds', 'user_facts': facts, 'assets': assets,
              'memory_status': status(job)}
    write(job / 'material-analysis.json', output)
    return {'analysis_path': str(job / 'material-analysis.json'), 'status': output['memory_status']}

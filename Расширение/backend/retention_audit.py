"""Read-only retention inventory. This tool never deletes or archives live rows.

Age is not evidence of financial completion. Old module_actions must retain
refund and client_action_id deduplication semantics before payloads can be purged.
"""
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3


def audit(path: Path, as_of: datetime) -> dict:
    if as_of.tzinfo is None:
        raise ValueError('as_of must include a timezone')
    as_of = as_of.astimezone(timezone.utc)
    cutoff_actions = (as_of - timedelta(days=14)).strftime('%Y-%m-%d %H:%M:%S')
    cutoff_events = (as_of - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    with closing(sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON'); db.execute('PRAGMA temp_store=MEMORY'); db.execute('BEGIN')
        cols = {r[1] for r in db.execute('PRAGMA table_info(module_actions)')}
        if not {'action_id','channel_id','module_id','status','client_action_id','created_at','data','error_msg'} <= cols:
            raise ValueError('Unexpected module_actions schema; inspect before planning retention')
        result = {'read_only':True, 'as_of_utc':as_of.isoformat(),
                  'actions_cutoff_utc':cutoff_actions, 'events_cutoff_utc':cutoff_events,
                  'snapshot_last_action_by_channel':dict(db.execute('SELECT channel_id,MAX(created_at) FROM module_actions GROUP BY channel_id').fetchall()),
                  'delete_authorized_by_this_report':False}
        result['aged_actions'] = [dict(zip(['channel_id','module_id','status','count'],r)) for r in db.execute(
            'SELECT channel_id,module_id,status,COUNT(*) FROM module_actions WHERE created_at<? GROUP BY channel_id,module_id,status', (cutoff_actions,))]
        result['aged_client_id_keys'] = db.execute('SELECT COUNT(*) FROM module_actions WHERE created_at<? AND client_action_id IS NOT NULL', (cutoff_actions,)).fetchone()[0]
        # These tables may have their own lifecycle and may still refer to old commands.
        result['references_to_aged_actions'] = []
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            if table == 'module_actions': continue
            quoted = '"'+table.replace('"','""')+'"'
            columns = {r[1] for r in db.execute('PRAGMA table_info('+quoted+')')}
            if not {'action_id','channel_id'} <= columns: continue
            # EXISTS avoids multiplying references if a damaged DB contains duplicate IDs.
            count = db.execute('SELECT COUNT(*) FROM '+quoted+' r WHERE EXISTS (SELECT 1 FROM module_actions a WHERE a.channel_id=r.channel_id AND a.action_id=r.action_id AND a.created_at<?)', (cutoff_actions,)).fetchone()[0]
            if count: result['references_to_aged_actions'].append({'table':table,'count':count})
        result['aged_event_counts'] = [dict(zip(['channel_id','count'],r)) for r in db.execute(
            'SELECT channel_id,COUNT(*) FROM bannerlord_events_log WHERE created_at<? GROUP BY channel_id', (cutoff_events,))]
        result['holds'] = ['No automatic module_actions deletion: preserve late refunds, dedup keys and domain references.',
                           'Keep points_ledger and activity_stats.',
                           'Archive audit events with verified restore before considering live deletion.']
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--as-of', required=True, help='ISO timestamp with timezone, e.g. 2026-09-27T00:00:00Z')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.db.resolve():
        parser.error('Output must not overwrite the source database')
    result = audit(args.db, datetime.fromisoformat(args.as_of.replace('Z','+00:00')))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Read-only retention inventory saved; no rows changed.')

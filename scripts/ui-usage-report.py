#!/usr/bin/env python3
"""Read-only UI intent report from an explicitly selected SQLite copy.

Example: python scripts/ui-usage-report.py --db ./copy.db --channel 98319857 --days 14
No production connection/default path, no identities or raw action payloads output.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3


def report(conn, channel_id, days=14, surface=None):
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=days - 1)).isoformat()
    base = 'channel_id=? AND day>=? AND day<=?'
    params = [channel_id, since, today.isoformat()]
    if surface:
        base += ' AND surface=?'
        params.append(surface)
    # Every CTE is tenant/window scoped. DISTINCT spans the whole interval; do
    # not sum daily unique counts (one viewer on ten days is still one viewer).
    rows = conn.execute(f'''WITH scoped AS (
        SELECT * FROM ui_feature_usage WHERE {base}
    ), eligible AS (
        SELECT * FROM scoped WHERE module_id='core' OR module_id=active_module
    ), panels AS (
        SELECT DISTINCT module_id, viewer_id FROM eligible WHERE kind='panel_view'
    )
    SELECT s.module_id, s.kind, s.feature_key, SUM(s.count),
           COUNT(DISTINCT s.viewer_id),
           SUM(CASE WHEN s.module_id='core' OR s.module_id=s.active_module THEN s.count ELSE 0 END),
           COUNT(DISTINCT CASE WHEN s.module_id='core' OR s.module_id=s.active_module THEN s.viewer_id END),
           COUNT(DISTINCT CASE WHEN (s.module_id='core' OR s.module_id=s.active_module) AND p.viewer_id IS NOT NULL THEN s.viewer_id END),
           (SELECT COUNT(*) FROM panels d WHERE d.module_id=s.module_id)
    FROM scoped s LEFT JOIN panels p ON p.module_id=s.module_id AND p.viewer_id=s.viewer_id
    GROUP BY s.module_id, s.kind, s.feature_key
    ORDER BY SUM(s.count) DESC, s.feature_key''', params).fetchall()
    features = []
    for module, kind, key, count, viewers, eligible_count, eligible_viewers, cohort_users, cohort in rows:
        features.append(dict(module=module, kind=kind, feature=key, count=count,
            unique_viewers=viewers, eligible_count=eligible_count,
            eligible_unique_viewers=eligible_viewers, panel_cohort_users=cohort_users,
            panel_cohort_viewers=cohort,
            panel_cohort_percent=round(100 * cohort_users / cohort, 2) if cohort else None))
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    accepted = []
    if 'feature_usage' in tables:
        accepted = [dict(feature=key, count=count) for key, count in conn.execute(
            'SELECT feature_key,SUM(count) FROM feature_usage WHERE channel_id=? AND day>=? AND day<=? GROUP BY feature_key ORDER BY SUM(count) DESC',
            (channel_id, since, today.isoformat()))]
    statuses = []
    if 'module_actions' in tables:
        statuses = [dict(feature=f'{module}:{key}', status=status, count=count) for module, key, status, count in conn.execute(
            'SELECT module_id,type,status,COUNT(*) FROM module_actions WHERE channel_id=? AND date(created_at)>=? AND date(created_at)<=? GROUP BY module_id,type,status',
            (channel_id, since, today.isoformat()))]
    return dict(channel_id=channel_id, since_utc=since, through_utc=today.isoformat(), surface=surface or 'all',
        coverage=dict(client='frontend-pilot-v1', identity='existing signed linked Twitch user_id',
            sections='explicit tab/section/details open hooks only; defaults, renders and polling excluded',
            actions='central ShedLink.buyAction attempted dispatch after auth, before duplicate guard; direct legacy/core endpoints are not instrumented',
            frozen_clients='0.0.5 and earlier do not emit UI counters; their absence is unknown, never zero usage',
            eligibility='core, or game module equals authoritative active_module at batch receipt; not proof the feature was visible/unlocked or mod online',
            denominator='distinct linked viewers with an observed eligible panel_view for the same module during this UTC window; numerator is intersection with that cohort',
            retention='90 UTC days of aggregates, 24 hours of retry IDs; expired rows pruned on the next ingestion for that channel',
            caveats='best-effort client claims can be lost/spoofed; 20-feature/100-count queue caps, bursts and token changes may drop counts; no recorded event is unknown rather than zero; no success/conversion rate across unlike cohorts'),
        ui_features=features, existing_server_accepted=accepted, existing_module_action_statuses=statuses,
        existing_statuses_available='module_actions' in tables,
        server_metric_note='existing accepted feature counts and queue/ACK statuses have broader client coverage and are reported separately; they are not UI attempts or verified game effects')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True, help='Explicit local SQLite snapshot, opened read-only')
    parser.add_argument('--channel', type=int, required=True)
    parser.add_argument('--days', type=int, default=14, choices=range(1, 91), metavar='1..90')
    parser.add_argument('--surface', choices=('desktop', 'mobile'))
    args = parser.parse_args()
    if args.channel <= 0:
        parser.error('--channel must be positive')
    try:
        with sqlite3.connect(args.db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
            result = report(conn, args.channel, args.days, args.surface)
    except sqlite3.Error as exc:
        parser.exit(1, f'Report unavailable: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Read-only production database checks after a ShedLink deployment."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


REQUIRED_MIGRATIONS = (
    "M109.module_last_seen",
    "M110.manager_credentials",
    "M111.manager_session_scope",
    "M112.manager_diagnostics",
)
REQUIRED_TABLES = (
    "module_last_seen",
    "manager_pairings",
    "manager_sessions",
    "module_credentials",
    "manager_diagnostic_actions",
)


def scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int | str:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()

    uri = f"file:{args.database.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=30) as conn:
        migrations = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM migrations_applied WHERE name IN (?,?,?,?)",
                REQUIRED_MIGRATIONS,
            )
        }
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN (?,?,?,?,?)",
                REQUIRED_TABLES,
            )
        }
        action_statuses = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM module_actions GROUP BY status"
            ).fetchall()
        )
        report = {
            "quick_check": scalar(conn, "PRAGMA quick_check"),
            "required_migrations": sorted(migrations),
            "missing_migrations": sorted(set(REQUIRED_MIGRATIONS) - migrations),
            "required_tables": sorted(tables),
            "missing_tables": sorted(set(REQUIRED_TABLES) - tables),
            "negative_viewer_points": scalar(
                conn, "SELECT COUNT(*) FROM viewers WHERE points < 0"
            ),
            "module_action_statuses": action_statuses,
            "module_last_seen_rows": scalar(conn, "SELECT COUNT(*) FROM module_last_seen"),
            "manager_pairings": scalar(conn, "SELECT COUNT(*) FROM manager_pairings"),
            "manager_sessions": scalar(conn, "SELECT COUNT(*) FROM manager_sessions"),
            "module_credentials": scalar(conn, "SELECT COUNT(*) FROM module_credentials"),
            "manager_diagnostics": scalar(
                conn, "SELECT COUNT(*) FROM manager_diagnostic_actions"
            ),
        }

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    healthy = (
        report["quick_check"] == "ok"
        and not report["missing_migrations"]
        and not report["missing_tables"]
        and report["negative_viewer_points"] == 0
    )
    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())

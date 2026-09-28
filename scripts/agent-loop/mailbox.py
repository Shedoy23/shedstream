#!/usr/bin/env python3
"""Local append-only mailbox for a Claude <-> Codex review loop.

This tool deliberately does not invoke either model and cannot deploy anything.
It gives GUI agents a shared, auditable handoff channel in the repository.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


AGENTS = ("owner", "claude", "codex")
TASK_MODES = ("delivery", "analysis")
KINDS = (
    "request",
    "plan",
    "implementation",
    "review",
    "resolution",
    "evidence",
    "blocked",
    "ready",
    "decision",
)
MAX_BODY_CHARS = 200_000
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"(?i)\b(?:oauth_(?:access|refresh)_token|client_secret|api_key)"
        r"\s*[:=]\s*[\"']?[A-Za-z0-9_.-]{20,}"
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def find_workspace(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit("No Git workspace found. Run this command inside the repository.")


def default_db_path() -> Path:
    return find_workspace() / ".agent-loop" / "mailbox.sqlite3"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id            TEXT PRIMARY KEY,
            title         TEXT NOT NULL,
            request       TEXT NOT NULL,
            created_by    TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            status        TEXT NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open', 'closed', 'blocked')),
            current_owner TEXT NOT NULL,
            mode          TEXT NOT NULL DEFAULT 'delivery'
                          CHECK (mode IN ('delivery', 'analysis')),
            max_rounds    INTEGER NOT NULL DEFAULT 2 CHECK (max_rounds BETWEEN 1 AND 10)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id         TEXT NOT NULL REFERENCES tasks(id),
            sender          TEXT NOT NULL,
            target          TEXT NOT NULL,
            kind            TEXT NOT NULL,
            body            TEXT NOT NULL,
            evidence_json   TEXT NOT NULL DEFAULT '[]',
            created_at      TEXT NOT NULL,
            acknowledged_at TEXT,
            idempotency_key TEXT UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_target_unread
        ON messages(target, acknowledged_at, id);

        CREATE TABLE IF NOT EXISTS activities (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id    TEXT NOT NULL REFERENCES tasks(id),
            agent      TEXT NOT NULL,
            kind       TEXT NOT NULL,
            message    TEXT NOT NULL,
            detail     TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_activities_task
        ON activities(task_id, id);
        """
    )
    add_column_if_missing(conn, "tasks", "claude_model", "TEXT")
    add_column_if_missing(conn, "tasks", "codex_model", "TEXT")
    add_column_if_missing(
        conn, "tasks", "mode", "TEXT NOT NULL DEFAULT 'delivery'"
    )
    return conn


def add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    """The chat server and a manual CLI run may migrate at the same moment;
    losing that race means the column already exists, which is not an error."""
    existing = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column in existing:
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    except sqlite3.OperationalError as exc:
        if "duplicate column" not in str(exc).lower():
            raise


@contextmanager
def open_db(db_path: Path):
    conn = connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def load_text(direct: str | None, file_name: str | None) -> str:
    if file_name:
        text = Path(file_name).resolve().read_text(encoding="utf-8")
    elif direct is not None:
        text = direct
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        raise SystemExit("Provide text with --body/--request, a file, or stdin.")
    text = text.strip()
    if not text:
        raise SystemExit("Message text cannot be empty.")
    if len(text) > MAX_BODY_CHARS:
        raise SystemExit(f"Message is too large (limit: {MAX_BODY_CHARS} characters).")
    screen_for_secrets(text)
    return text


def screen_for_secrets(text: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise SystemExit(
                "Potential secret detected. Store credentials outside the mailbox "
                "and refer to them by variable name only."
            )


def load_agent_policies() -> dict:
    path = Path(__file__).with_name("agents.json")
    return json.loads(path.read_text(encoding="utf-8"))


def task_or_die(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise SystemExit(f"Unknown task: {task_id}")
    return row


def command_init(args: argparse.Namespace) -> None:
    with open_db(args.db) as conn:
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name IN ('tasks','messages','activities')"
        ).fetchone()[0]
    print(json.dumps({"ok": tables == 3, "db": str(args.db)}, ensure_ascii=False))


def command_create(args: argparse.Namespace) -> None:
    request = load_text(args.request, args.request_file)
    task_id = args.id or f"SL-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:8]}"
    with open_db(args.db) as conn:
        conn.execute(
            """
            INSERT INTO tasks
                (id, title, request, created_by, created_at, current_owner,
                 mode, max_rounds, claude_model, codex_model)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                args.title.strip(),
                request,
                args.by,
                utc_now(),
                args.to,
                args.mode,
                args.max_rounds,
                args.claude_model,
                args.codex_model,
            ),
        )
        conn.execute(
            """
            INSERT INTO messages
                (task_id, sender, target, kind, body, evidence_json, created_at,
                 idempotency_key)
            VALUES (?, ?, ?, 'request', ?, '[]', ?, ?)
            """,
            (
                task_id,
                args.by,
                args.to,
                request,
                utc_now(),
                f"create:{task_id}",
            ),
        )
    print(json.dumps({"ok": True, "task_id": task_id, "next": args.to}))


def normalize_evidence(items: Iterable[str], workspace: Path) -> list[str]:
    result: list[str] = []
    for item in items:
        candidate = Path(item)
        if candidate.is_absolute():
            try:
                value = str(candidate.resolve().relative_to(workspace))
            except ValueError:
                value = str(candidate.resolve())
        else:
            value = str(candidate)
        screen_for_secrets(value)
        result.append(value.replace("\\", "/"))
    return result


def command_post(args: argparse.Namespace) -> None:
    body = load_text(args.body, args.body_file)
    workspace = find_workspace()
    evidence = normalize_evidence(args.evidence or (), workspace)
    with open_db(args.db) as conn:
        task = task_or_die(conn, args.task)
        if task["status"] != "open":
            raise SystemExit(f"Task {args.task} is {task['status']}; reopen it first.")
        if args.from_agent == args.to:
            raise SystemExit("Sender and target must be different.")
        try:
            cursor = conn.execute(
                """
                INSERT INTO messages
                    (task_id, sender, target, kind, body, evidence_json, created_at,
                     idempotency_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    args.task,
                    args.from_agent,
                    args.to,
                    args.kind,
                    body,
                    json.dumps(evidence, ensure_ascii=True),
                    utc_now(),
                    args.idempotency_key,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if args.idempotency_key and "idempotency_key" in str(exc):
                row = conn.execute(
                    "SELECT id FROM messages WHERE idempotency_key=?",
                    (args.idempotency_key,),
                ).fetchone()
                print(
                    json.dumps(
                        {"ok": True, "duplicate": True, "message_id": row["id"]}
                    )
                )
                return
            raise
        conn.execute(
            "UPDATE tasks SET current_owner=? WHERE id=?", (args.to, args.task)
        )
    print(
        json.dumps(
            {
                "ok": True,
                "message_id": cursor.lastrowid,
                "task_id": args.task,
                "next": args.to,
            }
        )
    )


def task_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    counts = conn.execute(
        """
        SELECT
            COUNT(*) AS messages,
            SUM(CASE WHEN kind='review' THEN 1 ELSE 0 END) AS reviews
        FROM messages WHERE task_id=?
        """,
        (row["id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "current_owner": row["current_owner"],
        "messages": counts["messages"],
        "reviews": counts["reviews"] or 0,
        "max_rounds": row["max_rounds"],
        "mode": row["mode"],
        "created_at": row["created_at"],
    }


def command_status(args: argparse.Namespace) -> None:
    with open_db(args.db) as conn:
        if args.task:
            rows = [task_or_die(conn, args.task)]
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC"
            ).fetchall()
        payload = [task_summary(conn, row) for row in rows]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def command_inbox(args: argparse.Namespace) -> None:
    with open_db(args.db) as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.task_id, t.title, m.sender, m.kind, m.body,
                   m.evidence_json, m.created_at
            FROM messages m
            JOIN tasks t ON t.id=m.task_id
            WHERE m.target=? AND m.acknowledged_at IS NULL AND t.status='open'
            ORDER BY m.id
            """,
            (args.agent,),
        ).fetchall()
        payload = [
            {
                "message_id": row["id"],
                "task_id": row["task_id"],
                "title": row["title"],
                "from": row["sender"],
                "kind": row["kind"],
                "body": row["body"],
                "evidence": json.loads(row["evidence_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def render_prompt(
    task: sqlite3.Row,
    messages: list[sqlite3.Row],
    agent: str,
    db_path: Path,
    reviews_before: int = 0,
) -> str:
    policies = load_agent_policies()
    mode = task["mode"] if "mode" in task.keys() else "delivery"
    lines = [
        f"# Agent handoff: {task['id']} - {task['title']}",
        "",
        f"You are **{agent}**, one participant in this task.",
    ]
    for guardrail in policies[agent].get("guardrails", []):
        lines.append(f"- {guardrail}")
    lines.extend(["", "## Owner request", "", task["request"], "", "## Thread"])
    if mode == "analysis":
        lines.extend(
            [
                "",
                "This is an analysis/audit task. Do not edit, create, delete, or "
                "rename files. Return an evidence-backed report to the owner.",
            ]
        )
    visible_messages = messages
    if agent == "codex" and reviews_before == 0:
        visible_messages = [
            message for message in messages if message["sender"] != "claude"
        ]
        lines.extend(
            [
                "",
                "The first review is blind. Claude's self-assessment and evidence "
                "are intentionally hidden; inspect the owner request and current "
                "worktree independently.",
            ]
        )
    for message in visible_messages:
        evidence = json.loads(message["evidence_json"])
        lines.extend(
            [
                "",
                f"### #{message['id']} {message['sender']} -> "
                f"{message['target']} [{message['kind']}]",
                "",
                message["body"],
            ]
        )
        if evidence:
            lines.extend(["", "Evidence:"])
            lines.extend(f"- {item}" for item in evidence)
    lines.extend(
        [
            "",
            "## Handoff rule",
            "",
            "After your work, post one concise evidence-backed message to the next "
            "actor. Do not include credentials. Example:",
            "",
            "```powershell",
            "python scripts/agent-loop/mailbox.py post "
            f"--db \"{db_path}\" --task {task['id']} --from {agent} "
            "--to <claude|codex|owner> --kind <kind> "
            "--body-file <handoff-file> --evidence <path>",
            "```",
        ]
    )
    return "\n".join(lines)


def command_next(args: argparse.Namespace) -> None:
    with open_db(args.db) as conn:
        task = None
        if args.task:
            task = task_or_die(conn, args.task)
            if task["status"] != "open":
                raise SystemExit(f"Task {args.task} is {task['status']}.")
        else:
            task = conn.execute(
                """
                SELECT DISTINCT t.*
                FROM tasks t
                LEFT JOIN messages m
                  ON m.task_id=t.id AND m.target=? AND m.acknowledged_at IS NULL
                WHERE t.status='open'
                  AND (t.current_owner=? OR m.id IS NOT NULL)
                ORDER BY t.created_at
                LIMIT 1
                """,
                (args.agent, args.agent),
            ).fetchone()
        if not task:
            print(f"No open work for {args.agent}.")
            return
        messages = conn.execute(
            "SELECT * FROM messages WHERE task_id=? ORDER BY id", (task["id"],)
        ).fetchall()
        reviews_before = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE task_id=? AND sender='codex'
                  AND kind IN ('review','ready','blocked')
                """,
                (task["id"],),
            ).fetchone()[0]
        )
        prompt = render_prompt(
            task, messages, args.agent, args.db, reviews_before
        )
        if args.ack:
            conn.execute(
                """
                UPDATE messages SET acknowledged_at=?
                WHERE task_id=? AND target=? AND acknowledged_at IS NULL
                """,
                (utc_now(), task["id"], args.agent),
            )
    print(prompt)


def command_ack(args: argparse.Namespace) -> None:
    with open_db(args.db) as conn:
        task_or_die(conn, args.task)
        cursor = conn.execute(
            """
            UPDATE messages SET acknowledged_at=?
            WHERE task_id=? AND target=? AND acknowledged_at IS NULL
            """,
            (utc_now(), args.task, args.agent),
        )
    print(json.dumps({"ok": True, "acknowledged": cursor.rowcount}))


def command_set_status(args: argparse.Namespace) -> None:
    if args.by != "owner":
        raise SystemExit("Only owner may close, block, or reopen a task.")
    with open_db(args.db) as conn:
        task_or_die(conn, args.task)
        conn.execute(
            "UPDATE tasks SET status=?, current_owner='owner' WHERE id=?",
            (args.status, args.task),
        )
    print(json.dumps({"ok": True, "task_id": args.task, "status": args.status}))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Shared local mailbox for Claude and Codex GUI agents."
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="Mailbox DB (default: .agent-loop)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize the local mailbox.")
    init.set_defaults(func=command_init)

    create = sub.add_parser("create", help="Create a task and route it.")
    create.add_argument("--id")
    create.add_argument("--title", required=True)
    create.add_argument("--by", choices=AGENTS, default="owner")
    create.add_argument("--to", choices=("claude", "codex"), default="claude")
    create.add_argument("--mode", choices=TASK_MODES, default="delivery")
    create.add_argument("--max-rounds", type=int, default=2, choices=range(1, 11))
    create.add_argument("--claude-model")
    create.add_argument("--codex-model")
    request_group = create.add_mutually_exclusive_group()
    request_group.add_argument("--request")
    request_group.add_argument("--request-file")
    create.set_defaults(func=command_create)

    post = sub.add_parser("post", help="Append a handoff message.")
    post.add_argument("--task", required=True)
    post.add_argument("--from", dest="from_agent", choices=AGENTS, required=True)
    post.add_argument("--to", choices=AGENTS, required=True)
    post.add_argument("--kind", choices=KINDS, required=True)
    body_group = post.add_mutually_exclusive_group()
    body_group.add_argument("--body")
    body_group.add_argument("--body-file")
    post.add_argument("--evidence", action="append", default=[])
    post.add_argument("--idempotency-key")
    post.set_defaults(func=command_post)

    status = sub.add_parser("status", help="Show task status.")
    status.add_argument("--task")
    status.set_defaults(func=command_status)

    inbox = sub.add_parser("inbox", help="Show unread messages for an agent.")
    inbox.add_argument("--agent", choices=AGENTS, required=True)
    inbox.set_defaults(func=command_inbox)

    next_task = sub.add_parser("next", help="Render the next agent prompt.")
    next_task.add_argument("--agent", choices=("claude", "codex"), required=True)
    next_task.add_argument("--task")
    next_task.add_argument(
        "--ack", action="store_true", help="Acknowledge included messages."
    )
    next_task.set_defaults(func=command_next)

    ack = sub.add_parser("ack", help="Acknowledge messages for an agent.")
    ack.add_argument("--task", required=True)
    ack.add_argument("--agent", choices=AGENTS, required=True)
    ack.set_defaults(func=command_ack)

    set_status = sub.add_parser("set-status", help="Close, block, or reopen.")
    set_status.add_argument("--task", required=True)
    set_status.add_argument("--by", choices=AGENTS, required=True)
    set_status.add_argument(
        "--status", choices=("open", "closed", "blocked"), required=True
    )
    set_status.set_defaults(func=command_set_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.db = (args.db or default_db_path()).resolve()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

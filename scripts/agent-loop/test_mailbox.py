#!/usr/bin/env python3
"""Smoke tests for the local agent mailbox."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


SCRIPT = Path(__file__).with_name("mailbox.py")
SPEC = importlib.util.spec_from_file_location("agent_loop_mailbox", SCRIPT)
assert SPEC and SPEC.loader
mailbox = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mailbox
SPEC.loader.exec_module(mailbox)


class MailboxSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "mailbox.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(self.db), *args],
            text=True,
            encoding="utf-8",
            capture_output=True,
        )
        if ok and result.returncode != 0:
            self.fail(f"Command failed: {result.stderr}\n{result.stdout}")
        return result

    def test_review_round_trip(self) -> None:
        self.run_cli("init")
        created = self.run_cli(
            "create",
            "--id",
            "SL-TEST-1",
            "--title",
            "Review a fix",
            "--request",
            "Implement a bounded fix and provide evidence.",
        )
        self.assertEqual(json.loads(created.stdout)["next"], "claude")

        claude_prompt = self.run_cli(
            "next", "--agent", "claude", "--task", "SL-TEST-1", "--ack"
        ).stdout
        self.assertIn("Implement a bounded fix", claude_prompt)

        self.run_cli(
            "post",
            "--task",
            "SL-TEST-1",
            "--from",
            "claude",
            "--to",
            "codex",
            "--kind",
            "implementation",
            "--body",
            "Implemented the fix. Focused test passes.",
            "--evidence",
            "tests/test_fix.py",
            "--idempotency-key",
            "impl-1",
        )
        duplicate = self.run_cli(
            "post",
            "--task",
            "SL-TEST-1",
            "--from",
            "claude",
            "--to",
            "codex",
            "--kind",
            "implementation",
            "--body",
            "Implemented the fix. Focused test passes.",
            "--idempotency-key",
            "impl-1",
        )
        self.assertTrue(json.loads(duplicate.stdout)["duplicate"])

        codex_prompt = self.run_cli(
            "next", "--agent", "codex", "--task", "SL-TEST-1", "--ack"
        ).stdout
        self.assertIn("one participant in this task", codex_prompt)
        self.assertNotIn("Independent reviewer", codex_prompt)
        self.assertIn("first review is blind", codex_prompt)
        self.assertNotIn("Implemented the fix", codex_prompt)
        self.assertNotIn("tests/test_fix.py", codex_prompt)

        self.run_cli(
            "post",
            "--task",
            "SL-TEST-1",
            "--from",
            "codex",
            "--to",
            "claude",
            "--kind",
            "review",
            "--body",
            "One reproducible issue remains.",
        )
        status = json.loads(
            self.run_cli("status", "--task", "SL-TEST-1").stdout
        )[0]
        self.assertEqual(status["current_owner"], "claude")
        self.assertEqual(status["reviews"], 1)

        self.run_cli(
            "set-status",
            "--task",
            "SL-TEST-1",
            "--by",
            "owner",
            "--status",
            "closed",
        )
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM tasks WHERE id='SL-TEST-1'"
                ).fetchone()[0],
                "closed",
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(tasks)")
            }
            self.assertIn("claude_model", columns)
            self.assertIn("codex_model", columns)
            self.assertIn("mode", columns)

    def test_analysis_mode_is_visible_in_status_and_prompt(self) -> None:
        self.run_cli("init")
        self.run_cli(
            "create",
            "--id",
            "SL-ANALYSIS",
            "--title",
            "Audit docs",
            "--request",
            "Inspect documents.",
            "--mode",
            "analysis",
        )
        prompt = self.run_cli(
            "next", "--agent", "claude", "--task", "SL-ANALYSIS"
        ).stdout
        self.assertIn("Do not edit, create, delete, or rename files", prompt)
        status = json.loads(
            self.run_cli("status", "--task", "SL-ANALYSIS").stdout
        )[0]
        self.assertEqual("analysis", status["mode"])

    def test_secret_is_rejected(self) -> None:
        self.run_cli("init")
        result = self.run_cli(
            "create",
            "--title",
            "Unsafe",
            "--request",
            "api_key=abcdefghijklmnopqrstuvwxyz123456",
            ok=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Potential secret", result.stderr)


class ConcurrentAccessTest(unittest.TestCase):
    """Two writers share one database: the chat server and a manual CLI run."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "mailbox.sqlite3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lock_wait_is_longer_than_a_single_agent_write(self) -> None:
        with closing(mailbox.connect(self.db)) as conn:
            timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertGreaterEqual(timeout_ms, 30_000)

    def test_column_migration_tolerates_a_racing_writer(self) -> None:
        with closing(mailbox.connect(self.db)) as conn:
            mailbox.add_column_if_missing(conn, "tasks", "claude_model", "TEXT")

    def test_evidence_is_screened_for_secrets(self) -> None:
        workspace = Path(self.temp.name)
        self.assertEqual(
            ["notes.md"],
            mailbox.normalize_evidence(["notes.md"], workspace),
        )
        with self.assertRaises(SystemExit):
            mailbox.normalize_evidence(
                ["notes.md=sk-abcdefghijklmnopqrstuvwx"],
                workspace,
            )


if __name__ == "__main__":
    unittest.main()

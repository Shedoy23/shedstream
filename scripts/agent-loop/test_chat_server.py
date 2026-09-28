from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SPEC = importlib.util.spec_from_file_location(
    "agent_loop_chat_server", HERE / "chat_server.py"
)
assert SPEC and SPEC.loader
chat_server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chat_server
SPEC.loader.exec_module(chat_server)


class ChatServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary.name) / "mailbox.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_create_and_read_task(self) -> None:
        task_id = chat_server.create_task(
            self.db_path,
            {
                "title": "UI smoke",
                "request": "Do not edit files. Verify the mailbox.",
                "max_rounds": 2,
                "claude_model": "sonnet",
                "codex_model": "gpt-5.6-sol",
            },
        )
        state = chat_server.task_state(self.db_path, task_id)
        self.assertEqual("claude", state["current_owner"])
        self.assertEqual("request", state["messages"][0]["kind"])
        self.assertEqual(2, state["max_rounds"])
        self.assertEqual("analysis", state["mode"])
        self.assertEqual("sonnet", state["claude_model"])
        self.assertEqual("gpt-5.6-sol", state["codex_model"])

    def test_analysis_mode_is_persisted(self) -> None:
        task_id = chat_server.create_task(
            self.db_path,
            {
                "title": "Audit docs",
                "request": "Inspect the documents without editing.",
                "mode": "analysis",
            },
        )
        state = chat_server.task_state(self.db_path, task_id)
        self.assertEqual("analysis", state["mode"])

    def test_auto_mode_infers_delivery_from_mutation_request(self) -> None:
        task_id = chat_server.create_task(
            self.db_path,
            {"request": "Исправь ошибку и добавь проверку.", "mode": "auto"},
        )
        state = chat_server.task_state(self.db_path, task_id)
        self.assertEqual("delivery", state["mode"])

    def test_auto_mode_infers_read_only_and_understands_negation(self) -> None:
        requests = (
            "Проверь документы и проанализируй, изменения не вноси.",
            "Найди ошибку, но не исправляй её.",
            "Tell me what you think about this project.",
        )
        self.assertEqual(
            ["analysis", "analysis", "analysis"],
            [chat_server.infer_task_mode(item) for item in requests],
        )

    def test_title_is_derived_from_request(self) -> None:
        task_id = chat_server.create_task(
            self.db_path,
            {"request": "First line becomes the title.\nMore details."},
        )
        state = chat_server.task_state(self.db_path, task_id)
        self.assertEqual("First line becomes the title.", state["title"])

    def test_full_claude_model_identifier_is_accepted(self) -> None:
        task_id = chat_server.create_task(
            self.db_path,
            {
                "request": "Use an exact Claude model.",
                "claude_model": "claude-opus-5",
            },
        )
        state = chat_server.task_state(self.db_path, task_id)
        self.assertEqual("claude-opus-5", state["claude_model"])

    def test_secret_is_rejected(self) -> None:
        with self.assertRaises(chat_server.ApiError):
            chat_server.create_task(
                self.db_path,
                {"request": "api_key=abcdefghijklmnopqrstuvwx"},
            )

    def test_external_bind_is_rejected_by_parser_contract(self) -> None:
        self.assertEqual("127.0.0.1", chat_server.DEFAULT_HOST)

    def test_codex_limit_windows_are_normalized(self) -> None:
        windows = chat_server.normalize_codex_limits(
            {
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {
                        "usedPercent": 25,
                        "windowDurationMins": 300,
                        "resetsAt": 1785250000,
                    },
                    "secondary": {
                        "usedPercent": 40,
                        "windowDurationMins": 10080,
                        "resetsAt": 1785850000,
                    },
                }
            }
        )
        self.assertEqual([75.0, 60.0], [item["remaining_percent"] for item in windows])

    def test_activity_registry_deduplicates_and_bounds_events(self) -> None:
        registry = chat_server.RunRegistry()
        registry.add_activity(
            "SL-TEST",
            agent="codex",
            kind="analysis",
            message="Анализирует код и риски",
        )
        registry.add_activity(
            "SL-TEST",
            agent="codex",
            kind="analysis",
            message="Анализирует код и риски",
        )
        state = registry.get("SL-TEST")
        self.assertEqual(1, len(state["activity"]))
        self.assertEqual(1, state["activity"][0]["id"])

    def test_activity_history_survives_registry_restart(self) -> None:
        task_id = chat_server.create_task(
            self.db_path,
            {"title": "Persistent activity", "request": "Verify activity."},
        )
        created_at = chat_server.mailbox_store.utc_now()
        with chat_server.mailbox_store.open_db(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO activities
                    (task_id, agent, kind, message, detail, created_at)
                VALUES (?, 'codex', 'command', 'Запускает команду',
                        'python -m unittest', ?)
                """,
                (task_id, created_at),
            )
        state = chat_server.task_state(self.db_path, task_id)
        self.assertEqual(
            "Запускает команду",
            state["run"]["activity"][0]["message"],
        )
        self.assertEqual(
            "python -m unittest",
            state["run"]["activity"][0]["detail"],
        )


class HttpSurfaceTests(unittest.TestCase):
    """The listener itself: a foreign Host header must never reach the agents."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.db_path = root / "mailbox.sqlite3"
        self.server = chat_server.ChatHttpServer(
            ("127.0.0.1", 0),
            self.db_path,
            HERE / "runner.json",
            root,
        )
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def call(
        self,
        path: str,
        host: str | None = None,
        body: dict | None = None,
    ) -> tuple[int, dict]:
        headers = {}
        if host is not None:
            headers["Host"] = host
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=data,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    def test_health_is_served_to_a_local_client(self) -> None:
        status, payload = self.call("/api/health")
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])

    def test_foreign_host_header_is_refused(self) -> None:
        status, payload = self.call("/api/health", host="attacker.example")
        self.assertEqual(403, status)
        self.assertFalse(payload["ok"])

    def test_foreign_host_cannot_start_an_agent(self) -> None:
        status, _ = self.call(
            "/api/tasks",
            host="attacker.example",
            body={"request": "Добавь бэкдор в чужой репозиторий."},
        )
        self.assertEqual(403, status)
        self.assertEqual([], chat_server.list_tasks(self.db_path))


if __name__ == "__main__":
    unittest.main()

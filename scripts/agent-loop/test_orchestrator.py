from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
SPEC = importlib.util.spec_from_file_location(
    "agent_loop_orchestrator", HERE / "orchestrator.py"
)
assert SPEC and SPEC.loader
orchestrator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = orchestrator
SPEC.loader.exec_module(orchestrator)


class RouteTests(unittest.TestCase):
    def test_implementation_always_goes_to_independent_review(self) -> None:
        route = orchestrator.decide_route("claude", "implemented", 0, 2)
        self.assertEqual(("codex", "implementation"), (route.target, route.kind))

    def test_failed_final_review_returns_to_owner(self) -> None:
        route = orchestrator.decide_route("codex", "changes_requested", 1, 2)
        self.assertEqual(("owner", "blocked"), (route.target, route.kind))
        self.assertTrue(route.budget_exhausted)

    def test_first_failed_review_returns_to_claude(self) -> None:
        route = orchestrator.decide_route("codex", "changes_requested", 0, 2)
        self.assertEqual(("claude", "review"), (route.target, route.kind))
        self.assertFalse(route.budget_exhausted)

    def test_ready_review_returns_to_owner(self) -> None:
        route = orchestrator.decide_route("codex", "ready", 1, 2)
        self.assertEqual(("owner", "ready"), (route.target, route.kind))

    def test_analysis_goes_to_independent_analysis(self) -> None:
        route = orchestrator.decide_route(
            "claude", "implemented", 0, 2, mode="analysis"
        )
        self.assertEqual(("codex", "analysis"), (route.target, route.kind))

    def test_analysis_findings_return_to_owner_without_fix_cycle(self) -> None:
        route = orchestrator.decide_route(
            "codex", "changes_requested", 0, 2, mode="analysis"
        )
        self.assertEqual(("owner", "ready"), (route.target, route.kind))
        self.assertFalse(route.budget_exhausted)


class OutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = {
            "outcome": "ready",
            "summary": "The implementation is ready.",
            "evidence": ["src/example.py"],
            "tests": ["python -m unittest: passed"],
            "findings": [],
        }

    def test_parse_claude_structured_output(self) -> None:
        wrapper = json.dumps({"structured_output": self.result})
        self.assertEqual(
            self.result,
            orchestrator.parse_claude_output(wrapper),
        )

    def test_parse_claude_stream_result(self) -> None:
        stream = "\n".join(
            [
                json.dumps({"type": "system", "subtype": "init"}),
                json.dumps(
                    {"type": "result", "structured_output": self.result}
                ),
            ]
        )
        self.assertEqual(self.result, orchestrator.parse_claude_output(stream))

    def test_missing_output_field_is_rejected(self) -> None:
        del self.result["tests"]
        with self.assertRaises(orchestrator.RunnerError):
            orchestrator.validate_result(self.result)

    def test_secret_in_output_is_rejected(self) -> None:
        self.result["summary"] = "api_key=abcdefghijklmnopqrstuvwx"
        with self.assertRaises(orchestrator.RunnerError):
            orchestrator.validate_result(self.result)


class PromptTests(unittest.TestCase):
    def test_reviewer_prompt_does_not_turn_missing_optional_tool_into_bug(
        self,
    ) -> None:
        class Row(dict):
            pass

        task = Row(
            id="SL-TEST",
            title="Review",
            request="Review the change.",
        )
        prompt = orchestrator.render_agent_prompt(task, [], "codex")
        self.assertIn("Missing optional tooling", prompt)
        self.assertIn("host PATH is intentionally inherited", prompt)
        self.assertIn("not classify a reviewer-environment limitation", prompt)

    def test_first_codex_review_hides_implementer_handoff(self) -> None:
        class Row(dict):
            pass

        task = Row(id="SL-TEST", title="Review", request="Review the change.")
        messages = [
            Row(
                id=1,
                sender="owner",
                target="claude",
                kind="request",
                body="Review the change.",
            ),
            Row(
                id=2,
                sender="claude",
                target="codex",
                kind="implementation",
                body="Claude believes the fix is perfect.",
            ),
        ]
        prompt = orchestrator.render_agent_prompt(task, messages, "codex", 0)
        self.assertIn("blind independent pass", prompt)
        self.assertNotIn("Claude believes the fix is perfect", prompt)

        verification = orchestrator.render_agent_prompt(
            task, messages, "codex", 1
        )
        self.assertIn("Claude believes the fix is perfect", verification)

    def test_analysis_prompt_has_no_static_implementer_role(self) -> None:
        class Row(dict):
            pass

        task = Row(
            id="SL-TEST",
            title="Audit docs",
            request="Inspect the documents.",
            mode="analysis",
        )
        prompt = orchestrator.render_agent_prompt(task, [], "claude")
        self.assertIn("without changing any file", prompt)
        self.assertNotIn("Primary implementer", prompt)

    def test_turn_budget_is_stated_as_a_number_not_as_advice(self) -> None:
        class Row(dict):
            pass

        task = Row(
            id="SL-TEST",
            title="Audit money path",
            request="Audit section 2 of the spec.",
            mode="analysis",
        )
        prompt = orchestrator.render_agent_prompt(task, [], "claude", 0, 45)
        self.assertIn("45 tool calls", prompt)
        self.assertIn("discards everything you found", prompt)
        # Codex has no turn cap, so it must not be told about one.
        self.assertNotIn("tool calls for this task", orchestrator.render_agent_prompt(
            task, [], "codex", 0, None
        ))


class ProgressTests(unittest.TestCase):
    def test_claude_tool_event_is_summarized_without_reasoning(self) -> None:
        activities = orchestrator.summarize_claude_event(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": "src/app.py"},
                            }
                        ]
                    },
                }
            )
        )
        self.assertEqual("Читает файл", activities[0]["message"])
        self.assertEqual("src/app.py", activities[0]["detail"])

    def test_codex_command_event_is_summarized(self) -> None:
        activities = orchestrator.summarize_codex_event(
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "type": "command_execution",
                        "command": "python -m unittest",
                    },
                }
            )
        )
        self.assertEqual("Запускает команду", activities[0]["message"])
        self.assertEqual("python -m unittest", activities[0]["detail"])

    def test_activity_detail_redacts_potential_secret(self) -> None:
        activities = orchestrator.summarize_codex_event(
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "type": "command_execution",
                        "command": "tool --api_key=abcdefghijklmnopqrstuvwxyz",
                    },
                }
            )
        )
        self.assertEqual(
            "[скрыто: возможный секрет]",
            activities[0]["detail"],
        )

    def test_streaming_process_reports_lines(self) -> None:
        lines: list[str] = []
        completed = orchestrator.run_process(
            [
                sys.executable,
                "-c",
                "print('first', flush=True); print('second', flush=True)",
            ],
            HERE,
            10,
            stdout_callback=lambda line: lines.append(line.strip()),
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual(["first", "second"], lines)


class CommandTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows npm shim behavior")
    def test_resolve_prefers_user_npm_shim_over_windowsapps(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            shim_dir = Path(temporary) / "npm"
            shim_dir.mkdir()
            shim = shim_dir / "codex.cmd"
            shim.write_text("@echo off\r\n", encoding="ascii")
            with mock.patch.dict(os.environ, {"APPDATA": temporary}):
                self.assertEqual([str(shim)], orchestrator.resolve_command("codex"))

    def test_reviewer_path_contains_current_python(self) -> None:
        entries = {
            Path(item).resolve()
            for item in orchestrator.reviewer_tool_path().split(os.pathsep)
        }
        self.assertIn(Path(sys.executable).resolve().parent, entries)

    def test_claude_analysis_command_has_no_write_or_shell_tools(self) -> None:
        result = {
            "outcome": "implemented",
            "summary": "Read-only analysis completed.",
            "evidence": ["README.md"],
            "tests": [],
            "findings": [],
        }
        completed = __import__("subprocess").CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"structured_output": result}),
            stderr="",
        )
        with mock.patch.object(
            orchestrator, "run_process", return_value=completed
        ) as runner:
            orchestrator.invoke_claude(
                ["claude"],
                {"max_turns": 20, "read_only_tools": ["Read", "Glob", "Grep"]},
                "Inspect docs.",
                HERE,
                10,
                read_only=True,
            )
        command = runner.call_args.args[0]
        self.assertEqual("Read,Glob,Grep", command[command.index("--tools") + 1])
        self.assertEqual("plan", command[command.index("--permission-mode") + 1])
        denied = command[command.index("--disallowedTools") + 1]
        self.assertIn("Edit", denied)
        self.assertIn("Write", denied)
        self.assertIn("Bash", denied)
        self.assertNotIn("--allowedTools", command)

    def test_max_turn_failure_is_concise(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "assistant", "message": {"content": []}}),
                json.dumps(
                    {
                        "type": "result",
                        "subtype": "error_max_turns",
                        "errors": ["Reached maximum number of turns (12)"],
                        "huge": "x" * 5000,
                    }
                ),
            ]
        )
        completed = __import__("subprocess").CompletedProcess(
            args=[], returncode=1, stdout=raw, stderr=""
        )
        detail = orchestrator.process_failure(completed)
        self.assertIn("turn budget", detail)
        self.assertNotIn('"huge"', detail)


class PromptDeliveryTests(unittest.TestCase):
    """The prompt carries owner text and model output: keep it out of argv."""

    MARKER = "MARKER-PROMPT-MUST-NOT-REACH-ARGV"

    def setUp(self) -> None:
        self.result = {
            "outcome": "ready",
            "summary": "Reviewed.",
            "evidence": ["README.md"],
            "tests": [],
            "findings": [],
        }

    def test_claude_prompt_travels_on_stdin(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"structured_output": self.result}),
            stderr="",
        )
        with mock.patch.object(
            orchestrator, "run_process", return_value=completed
        ) as runner:
            orchestrator.invoke_claude(
                ["claude"],
                {"max_turns": 20},
                self.MARKER,
                HERE,
                10,
            )
        command = runner.call_args.args[0]
        self.assertFalse([part for part in command if self.MARKER in str(part)])
        self.assertEqual(self.MARKER, runner.call_args.kwargs["stdin_text"])

    def test_codex_prompt_travels_on_stdin(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with tempfile.TemporaryDirectory() as temporary:
            output_path = Path(temporary) / "last-message.json"
            output_path.write_text(json.dumps(self.result), encoding="utf-8")
            with mock.patch.object(
                orchestrator, "run_process", return_value=completed
            ) as runner:
                orchestrator.invoke_codex(
                    ["codex"],
                    {"sandbox": "read-only"},
                    self.MARKER,
                    HERE,
                    10,
                    output_path,
                )
        command = runner.call_args.args[0]
        self.assertFalse([part for part in command if self.MARKER in str(part)])
        self.assertEqual(self.MARKER, runner.call_args.kwargs["stdin_text"])

    def test_run_process_delivers_stdin_without_streaming(self) -> None:
        completed = orchestrator.run_process(
            [sys.executable, "-c", "import sys; print(sys.stdin.read().strip()[::-1])"],
            HERE,
            60,
            stdin_text="abcdef",
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("fedcba", completed.stdout.strip())

    def test_run_process_delivers_stdin_while_streaming(self) -> None:
        lines: list[str] = []
        completed = orchestrator.run_process(
            [sys.executable, "-c", "import sys; print(sys.stdin.read().strip()[::-1])"],
            HERE,
            60,
            stdout_callback=lines.append,
            stdin_text="abcdef",
        )
        self.assertEqual(0, completed.returncode)
        self.assertEqual(["fedcba"], [line.strip() for line in lines if line.strip()])


class RunRecordTests(unittest.TestCase):
    def test_run_records_are_pruned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with mock.patch.object(orchestrator, "RUN_RECORD_KEEP", 3):
                for index in range(6):
                    orchestrator.write_run_record(
                        workspace,
                        f"SL-{index}",
                        "claude",
                        {"outcome": "ready"},
                        {},
                    )
            records = list((workspace / ".agent-loop" / "runs").glob("*.json"))
        self.assertEqual(3, len(records))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Local-only chat UI for the bounded Claude <-> Codex review loop."""

from __future__ import annotations

import argparse
import json
import queue
import re
import subprocess
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import mailbox as mailbox_store
import orchestrator


HERE = Path(__file__).resolve().parent
UI_ROOT = HERE / "ui"
MAX_REQUEST_BYTES = 220_000
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
PROCESS_LOCK = threading.Lock()
MODEL_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
READ_ONLY_DIRECTIVE = re.compile(
    r"(?:\b(?:изменен\w*\s+)?не\s+(?:исправ\w*|измен\w*|редактир\w*|трог\w*|созда\w*|"
    r"удал\w*|пиши\w*|вноси\w*)|\bбез\s+(?:изменен\w*|правок|"
    r"редактирования)|\bread[- ]only\b|\bdo not\s+(?:edit|change|modify|"
    r"write|fix)\b)",
    re.IGNORECASE,
)
DELIVERY_INTENT = re.compile(
    r"(?:\b(?:исправ\w*|почин\w*|добав\w*|реализ\w*|измен\w*|обнов\w*|"
    r"удал\w*|созда\w*|перепиш\w*|внедр\w*|допил\w*|замен\w*|"
    r"рефактор\w*)\b|\b(?:fix|implement|add|change|update|remove|create|"
    r"rewrite|refactor|build)\b)",
    re.IGNORECASE,
)
ANALYSIS_INTENT = re.compile(
    r"(?:\b(?:провер\w*|проанализ\w*|аудит\w*|ревью\w*|изуч\w*|"
    r"прочит\w*|разбер\w*|найд\w*|диагност\w*|триаж\w*|оцен\w*)\b|"
    r"\b(?:analy[sz]e|audit|review|inspect|read|investigate|diagnose|"
    r"triage|assess|find)\b)",
    re.IGNORECASE,
)
CLAUDE_MODELS = [
    {"id": "", "display_name": "По умолчанию"},
    {"id": "sonnet", "display_name": "Sonnet · последний доступный"},
    {"id": "opus", "display_name": "Opus · последний доступный"},
    {"id": "fable", "display_name": "Fable · последний доступный"},
]
CAPABILITIES_LOCK = threading.Lock()
CAPABILITIES_CACHE: dict[str, Any] = {"loaded_at": 0.0, "value": None}


class ApiError(ValueError):
    def __init__(self, message: str, status: int = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class RunRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, dict[str, Any]] = {}

    def set(self, task_id: str, **values: Any) -> None:
        with self._lock:
            state = self._states.setdefault(task_id, {})
            state.update(values)

    def get(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._states.get(task_id, {}))

    def claim(self, task_id: str) -> bool:
        with self._lock:
            state = self._states.setdefault(task_id, {})
            if state.get("running"):
                return False
            state.update(running=True, phase="queued", error=None)
            return True

    def add_activity(
        self,
        task_id: str,
        *,
        agent: str,
        kind: str,
        message: str,
        detail: str | None = None,
        event_id: int | None = None,
        created_at: str | None = None,
    ) -> bool:
        with self._lock:
            state = self._states.setdefault(task_id, {})
            activity = state.setdefault("activity", [])
            current = {
                "agent": agent,
                "kind": kind,
                "message": message,
                "detail": detail,
            }
            if activity and all(
                activity[-1].get(key) == value for key, value in current.items()
            ):
                return False
            sequence = event_id or int(state.get("activity_seq", 0)) + 1
            state["activity_seq"] = sequence
            activity.append(
                {
                    "id": sequence,
                    **current,
                    "created_at": created_at or mailbox_store.utc_now(),
                }
            )
            del activity[:-80]
            return True


RUNS = RunRegistry()


def read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.lower().startswith("application/json"):
        raise ApiError("Content-Type must be application/json.")
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise ApiError("Invalid Content-Length.") from exc
    if length <= 0 or length > MAX_REQUEST_BYTES:
        raise ApiError("Request body is empty or too large.")
    try:
        value = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError("Request body must be valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise ApiError("Request body must be a JSON object.")
    return value


def validate_model(value: Any, provider: str) -> str | None:
    model = str(value or "").strip()
    if not model:
        return None
    if not MODEL_NAME.fullmatch(model):
        raise ApiError(f"Некорректная модель {provider}.")
    return model


def infer_task_mode(request: str) -> str:
    """Resolve permissions before either model sees the request."""
    read_only = bool(READ_ONLY_DIRECTIVE.search(request))
    delivery_source = READ_ONLY_DIRECTIVE.sub(" ", request)
    if DELIVERY_INTENT.search(delivery_source):
        return "delivery"
    if read_only or ANALYSIS_INTENT.search(request):
        return "analysis"
    return "analysis"


def validate_task_input(
    payload: dict[str, Any],
) -> tuple[str, str, str, int, str | None, str | None]:
    request = str(payload.get("request", "")).strip()
    if not request:
        raise ApiError("Опиши задачу перед запуском.")
    if len(request) > mailbox_store.MAX_BODY_CHARS:
        raise ApiError("Задача слишком длинная.")
    for pattern in mailbox_store.SECRET_PATTERNS:
        if pattern.search(request):
            raise ApiError("Похоже, в задаче есть секрет или токен. Удали его.")
    title = str(payload.get("title", "")).strip()
    if not title:
        title = request.splitlines()[0][:80].strip()
    if not title:
        title = "Новая задача"
    if len(title) > 120:
        raise ApiError("Название задачи длиннее 120 символов.")
    requested_mode = str(payload.get("mode", "auto")).strip()
    if requested_mode not in (*mailbox_store.TASK_MODES, "auto"):
        raise ApiError("Неизвестный режим задачи.")
    mode = (
        infer_task_mode(request)
        if requested_mode == "auto"
        else requested_mode
    )
    try:
        max_rounds = int(payload.get("max_rounds", 2))
    except (TypeError, ValueError) as exc:
        raise ApiError("Число раундов должно быть целым.") from exc
    if max_rounds not in range(1, 11):
        raise ApiError("Допустимо от 1 до 10 раундов.")
    claude_model = validate_model(payload.get("claude_model"), "Claude")
    codex_model = validate_model(payload.get("codex_model"), "Codex")
    return title, request, mode, max_rounds, claude_model, codex_model


def create_task(db_path: Path, payload: dict[str, Any]) -> str:
    (
        title,
        request,
        mode,
        max_rounds,
        claude_model,
        codex_model,
    ) = validate_task_input(payload)
    task_id = f"SL-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:8]}"
    with mailbox_store.open_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tasks
                (id, title, request, created_by, created_at, current_owner,
                 mode, max_rounds, claude_model, codex_model)
            VALUES (?, ?, ?, 'owner', ?, 'claude', ?, ?, ?, ?)
            """,
            (
                task_id,
                title,
                request,
                mailbox_store.utc_now(),
                mode,
                max_rounds,
                claude_model,
                codex_model,
            ),
        )
        conn.execute(
            """
            INSERT INTO messages
                (task_id, sender, target, kind, body, evidence_json, created_at,
                 idempotency_key)
            VALUES (?, 'owner', 'claude', 'request', ?, '[]', ?, ?)
            """,
            (
                task_id,
                request,
                mailbox_store.utc_now(),
                f"create:{task_id}",
            ),
        )
    return task_id


def task_state(db_path: Path, task_id: str) -> dict[str, Any]:
    with mailbox_store.open_db(db_path) as conn:
        task = conn.execute(
            "SELECT * FROM tasks WHERE id=?", (task_id,)
        ).fetchone()
        if not task:
            raise ApiError("Задача не найдена.", HTTPStatus.NOT_FOUND)
        messages = conn.execute(
            "SELECT * FROM messages WHERE task_id=? ORDER BY id",
            (task_id,),
        ).fetchall()
        activities = conn.execute(
            "SELECT * FROM activities WHERE task_id=? ORDER BY id DESC LIMIT 80",
            (task_id,),
        ).fetchall()[::-1]
        reviews = orchestrator.count_reviews(conn, task_id)
    run_state = RUNS.get(task_id)
    run_state["activity"] = [
        {
            "id": row["id"],
            "agent": row["agent"],
            "kind": row["kind"],
            "message": row["message"],
            "detail": row["detail"],
            "created_at": row["created_at"],
        }
        for row in activities
    ]
    return {
        "id": task["id"],
        "title": task["title"],
        "request": task["request"],
        "status": task["status"],
        "current_owner": task["current_owner"],
        "mode": task["mode"],
        "max_rounds": task["max_rounds"],
        "claude_model": task["claude_model"],
        "codex_model": task["codex_model"],
        "reviews": reviews,
        "created_at": task["created_at"],
        "run": run_state,
        "messages": [
            {
                "id": row["id"],
                "sender": row["sender"],
                "target": row["target"],
                "kind": row["kind"],
                "body": row["body"],
                "evidence": json.loads(row["evidence_json"]),
                "created_at": row["created_at"],
            }
            for row in messages
        ],
    }


def list_tasks(db_path: Path) -> list[dict[str, Any]]:
    with mailbox_store.open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT t.*,
                   COUNT(m.id) AS message_count,
                   MAX(m.id) AS last_message_id
            FROM tasks t
            LEFT JOIN messages m ON m.task_id=t.id
            GROUP BY t.id
            ORDER BY COALESCE(MAX(m.id), 0) DESC
            LIMIT 100
            """
        ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "status": row["status"],
            "current_owner": row["current_owner"],
            "mode": row["mode"],
            "message_count": row["message_count"],
            "created_at": row["created_at"],
            "run": RUNS.get(row["id"]),
        }
        for row in rows
    ]


def normalize_codex_limits(result: dict[str, Any]) -> list[dict[str, Any]]:
    buckets = result.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict):
        single = result.get("rateLimits")
        buckets = {"codex": single} if isinstance(single, dict) else {}
    windows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for limit_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue
            minutes = window.get("windowDurationMins")
            used = window.get("usedPercent")
            reset = window.get("resetsAt")
            key = (limit_id, minutes, reset)
            if key in seen:
                continue
            seen.add(key)
            windows.append(
                {
                    "limit_id": limit_id,
                    "limit_name": bucket.get("limitName"),
                    "slot": slot,
                    "used_percent": used,
                    "remaining_percent": (
                        max(0, round(100 - float(used), 1))
                        if isinstance(used, (int, float))
                        else None
                    ),
                    "window_minutes": minutes,
                    "resets_at": reset,
                    "plan_type": bucket.get("planType"),
                }
            )
    windows.sort(key=lambda item: item.get("window_minutes") or 0)
    return windows


def read_codex_capabilities(config_path: Path) -> dict[str, Any]:
    config = orchestrator.load_json(config_path)
    command = [
        *orchestrator.resolve_command(str(config["codex"]["command"])),
        "app-server",
        "--listen",
        "stdio://",
    ]
    creationflags = (
        subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    )
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if not process.stdin or not process.stdout:
        process.kill()
        raise RuntimeError("Codex app-server stdio is unavailable.")
    output: queue.Queue[str] = queue.Queue()

    def read_output() -> None:
        assert process.stdout
        for line in process.stdout:
            output.put(line)

    threading.Thread(target=read_output, daemon=True).start()
    requests = [
        {
            "method": "initialize",
            "id": 1,
            "params": {
                "clientInfo": {
                    "name": "shedlink_agent_room",
                    "title": "ShedLink Agent Room",
                    "version": "1.0.0",
                }
            },
        },
        {"method": "initialized", "params": {}},
        {"method": "account/rateLimits/read", "id": 2},
        {
            "method": "model/list",
            "id": 3,
            "params": {"limit": 100, "includeHidden": False},
        },
    ]
    for request in requests:
        process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
    process.stdin.flush()
    responses: dict[int, dict[str, Any]] = {}
    deadline = time.monotonic() + 20
    try:
        while time.monotonic() < deadline and len(responses) < 2:
            try:
                line = output.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") in (2, 3):
                responses[int(message["id"])] = message
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
    rate_result = responses.get(2, {}).get("result", {})
    model_result = responses.get(3, {}).get("result", {})
    if not isinstance(rate_result, dict) or not isinstance(model_result, dict):
        raise RuntimeError("Codex app-server returned an incomplete response.")
    models = []
    for item in model_result.get("data", []):
        if not isinstance(item, dict) or item.get("hidden"):
            continue
        model_id = item.get("model") or item.get("id")
        if model_id:
            models.append(
                {
                    "id": model_id,
                    "display_name": item.get("displayName") or model_id,
                    "is_default": bool(item.get("isDefault")),
                }
            )
    return {
        "models": models,
        "limits": normalize_codex_limits(rate_result),
    }


def capabilities(config_path: Path, force: bool = False) -> dict[str, Any]:
    with CAPABILITIES_LOCK:
        cached = CAPABILITIES_CACHE.get("value")
        if (
            not force
            and cached
            and time.monotonic() - CAPABILITIES_CACHE["loaded_at"] < 60
        ):
            return cached
        try:
            codex = read_codex_capabilities(config_path)
            codex_error = None
        except Exception as exc:
            codex = {"models": [], "limits": []}
            codex_error = str(exc)
        value = {
            "models": {
                "claude": CLAUDE_MODELS,
                "codex": codex["models"],
            },
            "limits": {
                "codex": {
                    "available": bool(codex["limits"]),
                    "windows": codex["limits"],
                    "error": codex_error,
                },
                "claude": {
                    "available": False,
                    "message": (
                        "Точный остаток Claude доступен только через /usage "
                        "или Settings → Usage."
                    ),
                    "url": "https://claude.ai/settings/usage",
                },
            },
        }
        CAPABILITIES_CACHE.update(loaded_at=time.monotonic(), value=value)
        return value


def run_task(
    db_path: Path,
    config_path: Path,
    workspace: Path,
    task_id: str,
) -> None:
    RUNS.set(
        task_id,
        running=True,
        error=None,
        phase="starting",
        activity=[],
        activity_seq=0,
    )
    def publish_activity(event: dict[str, Any]) -> None:
        agent = str(event.get("agent") or "system")
        kind = str(event.get("kind") or "status")
        message = str(event.get("message") or "Работает")
        detail = (
            str(event["detail"]) if event.get("detail") is not None else None
        )
        current = RUNS.get(task_id).get("activity", [])
        if current and all(
            current[-1].get(key) == value
            for key, value in {
                "agent": agent,
                "kind": kind,
                "message": message,
                "detail": detail,
            }.items()
        ):
            return
        created_at = mailbox_store.utc_now()
        with mailbox_store.open_db(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO activities
                    (task_id, agent, kind, message, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, agent, kind, message, detail, created_at),
            )
            event_id = int(cursor.lastrowid)
        RUNS.add_activity(
            task_id,
            agent=agent,
            kind=kind,
            message=message,
            detail=detail,
            event_id=event_id,
            created_at=created_at,
        )

    publish_activity(
        {
            "agent": "system",
            "kind": "start",
            "message": "Готовит рабочее окружение",
        }
    )

    try:
        config = orchestrator.load_json(config_path)
        steps = int(config["max_steps"])
        with PROCESS_LOCK:
            with orchestrator.runner_lock(workspace):
                for _ in range(steps):
                    with mailbox_store.open_db(db_path) as conn:
                        task = conn.execute(
                            "SELECT current_owner, status FROM tasks WHERE id=?",
                            (task_id,),
                        ).fetchone()
                    if not task or task["status"] != "open":
                        break
                    owner = task["current_owner"]
                    if owner not in ("claude", "codex"):
                        break
                    RUNS.set(task_id, phase=owner)
                    publish_activity(
                        {
                            "agent": owner,
                            "kind": "handoff",
                            "message": (
                            "Принимает задачу в работу"
                            if owner == "claude"
                            else "Принимает независимую проверку"
                            ),
                        }
                    )
                    result = orchestrator.run_one(
                        db_path,
                        config,
                        workspace,
                        task_id,
                        False,
                        publish_activity,
                    )
                    RUNS.set(task_id, last_result=result)
                    next_actor = result.get("next")
                    if next_actor:
                        publish_activity(
                            {
                                "agent": "system",
                                "kind": "handoff",
                                "message": (
                                "Передаёт результат владельцу"
                                if next_actor == "owner"
                                else f"Передаёт ход агенту {next_actor.title()}"
                                ),
                            }
                        )
                    if result.get("next") == "owner" or result["state"] == "idle":
                        break
        publish_activity(
            {
                "agent": "system",
                "kind": "done",
                "message": "Автоматический цикл завершён",
            }
        )
        RUNS.set(task_id, running=False, phase="done")
    except Exception as exc:
        publish_activity(
            {
                "agent": "system",
                "kind": "error",
                "message": "Цикл остановлен",
                "detail": str(exc),
            }
        )
        RUNS.set(
            task_id,
            running=False,
            phase="error",
            error=str(exc),
        )


def start_task_thread(
    db_path: Path,
    config_path: Path,
    workspace: Path,
    task_id: str,
) -> bool:
    if not RUNS.claim(task_id):
        return False
    thread = threading.Thread(
        target=run_task,
        args=(db_path, config_path, workspace, task_id),
        name=f"agent-loop-{task_id}",
        daemon=True,
    )
    thread.start()
    return True


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "ShedLinkAgentLoop/1.0"

    @property
    def app(self) -> "ChatHttpServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[ui] {self.address_string()} {format % args}")

    def send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, exc: Exception) -> None:
        status = exc.status if isinstance(exc, ApiError) else 500
        self.send_json({"ok": False, "error": str(exc)}, status)

    def require_local_host(self) -> None:
        """Binding to loopback is not enough: a page whose domain resolves to
        127.0.0.1 reaches us as same-origin, so the Host header is the gate."""
        if self.headers.get("Host", "") not in self.app.allowed_hosts:
            raise ApiError(
                "Запрос отклонён: неизвестный заголовок Host.",
                HTTPStatus.FORBIDDEN,
            )

    def do_GET(self) -> None:
        try:
            self.require_local_host()
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                query = parse_qs(parsed.query)
                task_id = query.get("task", [None])[0]
                payload: dict[str, Any] = {
                    "ok": True,
                    "tasks": list_tasks(self.app.db_path),
                }
                if task_id:
                    payload["task"] = task_state(self.app.db_path, task_id)
                self.send_json(payload)
                return
            if parsed.path == "/api/health":
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/capabilities":
                query = parse_qs(parsed.query)
                self.send_json(
                    {
                        "ok": True,
                        **capabilities(
                            self.app.config_path,
                            force=query.get("refresh", ["0"])[0] == "1",
                        ),
                    }
                )
                return
            self.serve_static(parsed.path)
        except Exception as exc:
            self.send_error_json(exc)

    def do_POST(self) -> None:
        try:
            self.require_local_host()
            payload = read_json_body(self)
            parsed = urlparse(self.path)
            parts = [unquote(part) for part in parsed.path.split("/") if part]
            if parts == ["api", "tasks"]:
                task_id = create_task(self.app.db_path, payload)
                start_task_thread(
                    self.app.db_path,
                    self.app.config_path,
                    self.app.workspace,
                    task_id,
                )
                self.send_json(
                    {"ok": True, "task_id": task_id},
                    HTTPStatus.CREATED,
                )
                return
            if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                task_id, action = parts[2], parts[3]
                task_state(self.app.db_path, task_id)
                if action == "run":
                    started = start_task_thread(
                        self.app.db_path,
                        self.app.config_path,
                        self.app.workspace,
                        task_id,
                    )
                    self.send_json({"ok": True, "started": started})
                    return
                if action == "close":
                    with mailbox_store.open_db(self.app.db_path) as conn:
                        conn.execute(
                            """
                            UPDATE tasks
                            SET status='closed', current_owner='owner'
                            WHERE id=?
                            """,
                            (task_id,),
                        )
                    self.send_json({"ok": True})
                    return
            raise ApiError("Неизвестная команда.", HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_error_json(exc)

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path[1:]
        candidate = (UI_ROOT / relative).resolve()
        try:
            candidate.relative_to(UI_ROOT.resolve())
        except ValueError as exc:
            raise ApiError("Файл не найден.", HTTPStatus.NOT_FOUND) from exc
        if not candidate.is_file():
            raise ApiError("Файл не найден.", HTTPStatus.NOT_FOUND)
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".png": "image/png",
        }
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header(
            "Content-Type",
            content_types.get(candidate.suffix.lower(), "application/octet-stream"),
        )
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ChatHttpServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        db_path: Path,
        config_path: Path,
        workspace: Path,
    ):
        super().__init__(address, ChatHandler)
        self.db_path = db_path
        self.config_path = config_path
        self.workspace = workspace
        self.allowed_hosts = {
            f"{name}:{self.server_port}"
            for name in ("127.0.0.1", "localhost", "[::1]")
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local ShedLink agent chat UI.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=mailbox_store.default_db_path())
    parser.add_argument("--config", type=Path, default=orchestrator.DEFAULT_CONFIG)
    parser.add_argument(
        "--workspace",
        type=Path,
        default=mailbox_store.find_workspace(),
    )
    parser.add_argument("--open", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("For safety, the chat UI may only bind to localhost.")
    server = ChatHttpServer(
        (args.host, args.port),
        args.db.resolve(),
        args.config.resolve(),
        args.workspace.resolve(),
    )
    url = f"http://{args.host}:{server.server_port}"
    print(f"ShedLink agent chat: {url}")
    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

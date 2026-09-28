"""
logging_setup.py — structured JSON logging для production observability.

Sprint 5.33 PHASE1-3 (2026-05-28, architectural audit follow-up):
audit выявил отсутствие structured logging как operational gap. Production
log search через grep on plaintext = nightmare; JSON позволяет ingestion в
Loki/Elasticsearch/Datadog/etc.

Toggle:
    LOG_FORMAT=json  → JSON formatter (structured)
    LOG_FORMAT=text  → human-readable (default — for dev)
    LOG_LEVEL=DEBUG  → verbose
    LOG_LEVEL=INFO   → standard (default)

Each JSON log line:
  {ts: ISO8601, lvl: "INFO"|..., logger: "rimlink.routes.X",
   msg: "...", file: "main.py:123", thread: "...", exc?: traceback}

Если exception in record — adds `exc` field с stack trace.

Setup is idempotent — safe to call multiple times.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import traceback


class JsonFormatter(logging.Formatter):
    """One-line JSON per log record. Compatible с Loki/ELK/Datadog ingest."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            entry = {
                "ts":     self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "lvl":    record.levelname,
                "logger": record.name,
                "msg":    record.getMessage(),
                "file":   f"{record.filename}:{record.lineno}",
            }
            # Thread name useful для tracing concurrent flows
            if record.threadName and record.threadName != "MainThread":
                entry["thread"] = record.threadName
            # Exception/error stack — append если present
            if record.exc_info:
                entry["exc"] = "".join(traceback.format_exception(*record.exc_info))
            elif record.exc_text:
                entry["exc"] = record.exc_text
            # Extra fields from logger.info("msg", extra={"foo": 1})
            for key, val in record.__dict__.items():
                if key in (
                    "name", "msg", "args", "levelname", "levelno", "pathname",
                    "filename", "module", "exc_info", "exc_text", "stack_info",
                    "lineno", "funcName", "created", "msecs", "relativeCreated",
                    "thread", "threadName", "processName", "process",
                    "asctime", "message", "taskName",
                ):
                    continue
                # Только JSON-serializable extras
                try:
                    json.dumps(val)
                    entry[key] = val
                except (TypeError, ValueError):
                    entry[key] = repr(val)[:200]
            return json.dumps(entry, ensure_ascii=False, default=str)
        except Exception as ex:
            # Fallback: never let logging crash — emit best-effort text
            return f'{{"lvl":"ERROR","msg":"JsonFormatter crashed: {ex}","raw":"{record.getMessage()}"}}'


def setup_logging(force_format: str | None = None) -> None:
    """Configure root logger. Idempotent.

    force_format: 'json' / 'text'. Если None — читает env LOG_FORMAT.
    """
    fmt = (force_format or os.getenv("LOG_FORMAT", "text")).lower()
    level = os.getenv("LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    # Clear existing handlers если повторный вызов
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(stream=sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    # Quiet noisy libraries
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

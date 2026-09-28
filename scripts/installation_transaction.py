# -*- coding: utf-8 -*-
"""Reference filesystem transaction for a future ShedLink Manager installer.

The module deliberately has no UI or game-specific logic. A future Manager core
can either use it or treat its behavior/tests as the conformance contract.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Callable, Optional


Verifier = Callable[[Path], None]
Failpoint = Optional[Callable[[str], None]]


def _within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes allowed root: {path}") from exc
    return resolved


def _paths(target: Path) -> tuple[Path, Path, Path]:
    parent = target.parent
    name = target.name
    return (
        parent / f".{name}.shedlink-stage",
        parent / f".{name}.shedlink-backup",
        parent / f".{name}.shedlink-transaction.json",
    )


def _remove_tree(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _write_phase(journal: Path, phase: str) -> None:
    temporary = journal.with_suffix(journal.suffix + ".tmp")
    temporary.write_text(json.dumps({"phase": phase}), encoding="utf-8")
    os.replace(temporary, journal)


def _reject_symlinks(source: Path) -> None:
    if source.is_symlink():
        raise ValueError(f"source directory is a symlink: {source}")
    for child in source.rglob("*"):
        if child.is_symlink():
            raise ValueError(f"source contains symlink: {child}")


def recover_interrupted_install(target: Path, allowed_root: Path) -> bool:
    """Roll back an unfinished transaction. Returns True when recovery ran."""
    target = _within(target, allowed_root)
    stage, backup, journal = _paths(target)
    for path in (stage, backup, journal):
        _within(path, allowed_root)

    if not journal.exists():
        return False

    try:
        phase = json.loads(journal.read_text(encoding="utf-8")).get("phase")
    except (OSError, ValueError, AttributeError):
        phase = None

    # Safe policy: an unfinalized transaction always returns to the old version.
    if backup.exists():
        _remove_tree(target)
        os.replace(backup, target)
    elif phase in {"backed_up", "installed"}:
        # Fresh install had no previous target to restore.
        _remove_tree(target)
    _remove_tree(stage)
    journal.unlink(missing_ok=True)
    journal.with_suffix(journal.suffix + ".tmp").unlink(missing_ok=True)
    return True


def atomic_replace_directory(
    source: Path,
    target: Path,
    allowed_root: Path,
    verify: Verifier,
    failpoint: Failpoint = None,
) -> None:
    """Verify a staged copy, atomically replace target, and retain rollback safety."""
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"source directory does not exist: {source}")
    _reject_symlinks(source)

    target = _within(target, allowed_root)
    stage, backup, journal = _paths(target)
    for path in (stage, backup, journal):
        _within(path, allowed_root)
    if target == allowed_root.resolve():
        raise ValueError("installation target cannot be the allowed root")
    if target.is_symlink():
        raise ValueError("installation target cannot be a symlink")

    recover_interrupted_install(target, allowed_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    _remove_tree(stage)
    _remove_tree(backup)

    try:
        shutil.copytree(source, stage)
        verify(stage)
        _write_phase(journal, "prepared")
        if failpoint:
            failpoint("prepared")

        if target.exists():
            os.replace(target, backup)
        _write_phase(journal, "backed_up")
        if failpoint:
            failpoint("backed_up")

        os.replace(stage, target)
        _write_phase(journal, "installed")
        if failpoint:
            failpoint("installed")

        _remove_tree(backup)
        journal.unlink(missing_ok=True)
    except Exception:
        recovered = recover_interrupted_install(target, allowed_root)
        if not recovered:
            _remove_tree(stage)
        raise

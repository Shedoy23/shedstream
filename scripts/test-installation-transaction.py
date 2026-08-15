# -*- coding: utf-8 -*-
"""Conformance tests for atomic install, interruption recovery and rollback."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "scripts" / "installation_transaction.py"
SPEC = importlib.util.spec_from_file_location("installation_transaction", MODULE_PATH)
transaction = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(transaction)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


class HardInterruption(BaseException):
    pass


def content(path: Path) -> str:
    return (path / "version.txt").read_text(encoding="utf-8")


def verify_candidate(path: Path) -> None:
    if content(path) != "new":
        raise ValueError("unexpected staged content")


def fail_at(expected: str, hard: bool = False):
    def callback(actual: str) -> None:
        if actual == expected:
            if hard:
                raise HardInterruption(expected)
            raise RuntimeError(expected)
    return callback


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="shedlink-install-test-") as temp:
        base = Path(temp)
        game_root = base / "game"
        source = base / "source"
        target = game_root / "Mods" / "RimLink"
        source.mkdir()
        (source / "version.txt").write_text("new", encoding="utf-8")
        target.mkdir(parents=True)
        (target / "version.txt").write_text("old", encoding="utf-8")

        try:
            transaction.atomic_replace_directory(
                source, base / "outside" / "RimLink", game_root, verify_candidate
            )
            raise AssertionError("outside target was accepted")
        except ValueError:
            print("OK target outside game root is rejected")

        bad_source = base / "bad-source"
        bad_source.mkdir()
        (bad_source / "version.txt").write_text("corrupt", encoding="utf-8")
        try:
            transaction.atomic_replace_directory(
                bad_source, target, game_root, verify_candidate
            )
            raise AssertionError("failed verification was ignored")
        except ValueError:
            pass
        stage, _, _ = transaction._paths(target)
        assert content(target) == "old" and not stage.exists()
        print("OK failed staging verification leaves target untouched")

        try:
            transaction.atomic_replace_directory(
                source, target, game_root, verify_candidate, fail_at("backed_up")
            )
            raise AssertionError("injected failure was ignored")
        except RuntimeError:
            pass
        assert content(target) == "old"
        print("OK ordinary failure rolls back old version")

        try:
            transaction.atomic_replace_directory(
                source, target, game_root, verify_candidate,
                fail_at("backed_up", hard=True),
            )
        except HardInterruption:
            pass
        assert not target.exists()
        assert transaction.recover_interrupted_install(target, game_root)
        assert content(target) == "old"
        print("OK hard interruption is recovered on next startup")

        fresh_target = game_root / "Mods" / "FreshRimLink"
        try:
            transaction.atomic_replace_directory(
                source, fresh_target, game_root, verify_candidate,
                fail_at("installed", hard=True),
            )
        except HardInterruption:
            pass
        assert fresh_target.exists()
        assert transaction.recover_interrupted_install(fresh_target, game_root)
        assert not fresh_target.exists()
        print("OK interrupted fresh install is removed on recovery")

        transaction.atomic_replace_directory(
            source, target, game_root, verify_candidate
        )
        assert content(target) == "new"
        stage, backup, journal = transaction._paths(target)
        assert not stage.exists() and not backup.exists() and not journal.exists()
        print("OK successful install atomically replaces and cleans transaction files")

    print("ALL GREEN — interrupted install and rollback contract passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)

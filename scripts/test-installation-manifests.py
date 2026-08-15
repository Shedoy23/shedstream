# -*- coding: utf-8 -*-
"""Negative tests for the Installation Manifest schema and artefact validator."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parent.parent
VALIDATOR_PATH = ROOT / "scripts" / "validate-installation-manifests.py"
SPEC = importlib.util.spec_from_file_location("installation_validator", VALIDATOR_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def expect_failure(label: str, function, exception=Exception) -> None:
    try:
        function()
    except exception:
        print(f"OK {label}")
        return
    raise AssertionError(f"expected failure: {label}")


def main() -> int:
    schema = json.loads(validator.SCHEMA_PATH.read_text(encoding="utf-8"))
    manifest_path = validator.MANIFEST_DIR / "rimworld-0.1.0.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_validator = jsonschema.Draft202012Validator(schema)

    unknown = copy.deepcopy(manifest)
    unknown["installer_command"] = "arbitrary.exe"
    expect_failure(
        "unknown/executable fields are rejected",
        lambda: schema_validator.validate(unknown),
        jsonschema.ValidationError,
    )

    escaping = copy.deepcopy(manifest)
    escaping["artifacts"][0]["source"]["path"] = "../outside.zip"
    expect_failure(
        "repository path traversal is rejected by schema",
        lambda: schema_validator.validate(escaping),
        jsonschema.ValidationError,
    )

    wrong_hash = copy.deepcopy(manifest)
    wrong_hash["artifacts"][0]["sha256"] = "0" * 64
    fd, wrong_hash_path = tempfile.mkstemp(suffix=".json", prefix="manifest-bad-hash-")
    os.close(fd)
    try:
        Path(wrong_hash_path).write_text(
            json.dumps(wrong_hash), encoding="utf-8"
        )
        expect_failure(
            "artefact SHA-256 mismatch is rejected",
            lambda: validator.validate_manifest(Path(wrong_hash_path), schema),
            ValueError,
        )
    finally:
        Path(wrong_hash_path).unlink(missing_ok=True)

    fd, unsafe_zip_path = tempfile.mkstemp(suffix=".zip", prefix="manifest-unsafe-")
    os.close(fd)
    try:
        with zipfile.ZipFile(unsafe_zip_path, "w") as archive:
            archive.writestr("RimLink/../../outside.txt", "unsafe")
        expect_failure(
            "ZIP path traversal is rejected",
            lambda: validator.validate_archive(Path(unsafe_zip_path), "RimLink"),
            ValueError,
        )
    finally:
        Path(unsafe_zip_path).unlink(missing_ok=True)

    validator.validate_manifest(manifest_path, schema)
    print("OK canonical RimWorld manifest remains valid")
    print("ALL GREEN — Installation Manifest negative validation tests passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)

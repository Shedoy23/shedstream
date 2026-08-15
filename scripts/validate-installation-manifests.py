# -*- coding: utf-8 -*-
"""Validate Installation Manifest v1 plus repository-backed artefacts."""
from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath

try:
    import jsonschema
except ImportError:
    print("Install validator: python -m pip install -r scripts/requirements-manifest.txt")
    raise


ROOT = Path(__file__).resolve().parent.parent
MANIFEST_DIR = ROOT / "manifests" / "installation"
SCHEMA_PATH = MANIFEST_DIR / "v1.schema.json"

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def fail(message: str) -> None:
    raise ValueError(message)


def repository_path(relative: str) -> Path:
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        fail(f"artefact escapes repository: {relative}")
    return path


def validate_archive(path: Path, archive_root: str) -> None:
    root = archive_root.rstrip("/\\") + "/"
    with zipfile.ZipFile(path) as archive:
        if not archive.infolist():
            fail(f"empty ZIP: {path}")
        for entry in archive.infolist():
            normalized = entry.filename.replace("\\", "/")
            member = PurePosixPath(normalized)
            if member.is_absolute() or ".." in member.parts:
                fail(f"unsafe ZIP member: {entry.filename}")
            if normalized.rstrip("/") != archive_root and not normalized.startswith(root):
                fail(f"ZIP member outside archive_root '{archive_root}': {entry.filename}")


def validate_manifest(path: Path, schema: dict) -> None:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)

    if manifest["integration_id"] != manifest["game"]["id"]:
        fail(f"{path.name}: integration_id and game.id differ")
    if manifest["release_version"] != manifest["runtime"]["manifest_version"]:
        fail(f"{path.name}: release/runtime versions differ")

    for artifact in manifest["artifacts"]:
        source = artifact["source"]
        if source["kind"] != "repository":
            continue
        artifact_path = repository_path(source["path"])
        if not artifact_path.is_file():
            fail(f"{path.name}: missing artefact {source['path']}")
        if artifact_path.stat().st_size != artifact["size_bytes"]:
            fail(f"{path.name}: size mismatch for {source['path']}")
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != artifact["sha256"]:
            fail(f"{path.name}: SHA-256 mismatch for {source['path']}")
        if artifact["format"] == "zip":
            validate_archive(artifact_path, artifact["archive_root"])


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    manifests = sorted(
        path for path in MANIFEST_DIR.glob("*.json") if path != SCHEMA_PATH
    )
    if not manifests:
        fail("no installation manifests found")
    for manifest in manifests:
        validate_manifest(manifest, schema)
        print(f"OK {manifest.relative_to(ROOT)}")
    print(f"ALL GREEN — {len(manifests)} installation manifest(s) valid")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)

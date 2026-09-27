"""Verified, compressed SQLite snapshots. No third-party Python dependencies.

Use installed zstd at level 3, otherwise stdlib gzip level 1. A final pathname
appears only after SQLite quick_check and a full decompression/SHA256 check.
Existing snapshots survive every failure before publication.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time

RESERVE_BYTES = 200 * 1024 * 1024
CHUNK = 1024 * 1024


def require_space(directory: Path, additional: int) -> None:
    # Errors propagate: an unknown free-space value is not permission to write.
    free = shutil.disk_usage(directory).free
    required = max(0, additional) + RESERVE_BYTES
    if free < required:
        raise OSError(f'Not enough disk space: {free} bytes free, {required} required')


def digest_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(CHUNK), b''):
        digest.update(chunk)
    return digest.hexdigest()


def _sync_directory(directory: Path) -> None:
    # Linux production: make the new name durable as well as atomically visible.
    # Windows has no portable directory-fsync in Python; restore tests still run.
    if os.name != 'nt':
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _compress(raw: Path, archive: Path, zstd: str | None) -> None:
    if zstd:
        with archive.open('xb') as target:
            subprocess.run([zstd, '-q', '-3', '-c', str(raw)], stdout=target,
                           stderr=subprocess.PIPE, check=True, timeout=300)
    else:
        with raw.open('rb') as source, archive.open('xb') as target:
            with gzip.GzipFile(filename='', fileobj=target, mode='wb', compresslevel=1, mtime=0) as packed:
                shutil.copyfileobj(source, packed, CHUNK)


def _archive_digest(archive: Path, zstd: str | None) -> str:
    if not zstd:
        with gzip.open(archive, 'rb') as stream:
            return digest_stream(stream)
    # stderr goes to a file, so a failing decoder cannot deadlock its stdout.
    with tempfile.TemporaryFile() as errors:
        with subprocess.Popen([zstd, '-q', '-d', '-c', str(archive)],
                              stdout=subprocess.PIPE, stderr=errors) as process:
            try:
                digest = digest_stream(process.stdout)
                code = process.wait()
            except BaseException:
                process.kill(); process.wait()
                raise
            if code:
                raise RuntimeError(f'zstd decompression failed ({code})')
    return digest


def create_snapshot(source: Path, destination_base: Path) -> dict:
    """destination_base ends in .db; returns actual .db.zst or .db.gz path."""
    started = time.monotonic()
    source = Path(source).resolve(strict=True)
    base = Path(destination_base).resolve()
    if not source.is_file():
        raise ValueError('Source must be an existing SQLite file')
    if base.suffix != '.db' or source in (base, Path(str(base)+'.gz'), Path(str(base)+'.zst')):
        raise ValueError('Destination must be a different .db base path')
    parent = base.parent
    parent.mkdir(parents=True, exist_ok=True)
    zstd = shutil.which('zstd')
    final = Path(str(base) + ('.zst' if zstd else '.gz'))
    # Temporary files stay on the destination filesystem, permitting atomic rename.
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True, timeout=5)) as src:
        src.execute('PRAGMA query_only=ON')
        size = src.execute('PRAGMA page_count').fetchone()[0] * src.execute('PRAGMA page_size').fetchone()[0]
        if not src.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
            raise ValueError('Refusing to publish an empty database')
        # Raw snapshot + worst-case compressed output + working reserve.
        require_space(parent, 2 * size + size // 20 + CHUNK)
        with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=parent) as directory:
            temporary = Path(directory).resolve()
            if temporary.parent != parent:
                raise ValueError('Temporary path escaped destination directory')
            raw = temporary / 'snapshot.db'
            archive = temporary / 'snapshot.partial'
            with closing(sqlite3.connect(raw)) as dst:
                def progress(status, remaining, total):
                    require_space(parent, 0)
                    if time.monotonic() - started > 300:
                        raise TimeoutError('SQLite backup exceeded five minutes')
                src.backup(dst, pages=256, progress=progress, sleep=0.05)
                if dst.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    raise ValueError('SQLite backup quick_check failed')
            size = raw.stat().st_size
            require_space(parent, size + size // 20 + CHUNK)
            with raw.open('rb') as stream:
                digest = digest_stream(stream)
            _compress(raw, archive, zstd)
            if _archive_digest(archive, zstd) != digest:
                raise ValueError('Compressed backup SHA256 mismatch')
            with archive.open('rb+') as stream:
                stream.flush(); os.fsync(stream.fileno())
            archive_size = archive.stat().st_size
            require_space(parent, 0)
            os.replace(archive, final)
            _sync_directory(parent)
            # The owned temporary directory is removed even after exceptions.
    return {'path': str(final), 'size_bytes': archive_size, 'raw_size_bytes': size,
            'sha256': digest, 'duration_s': time.monotonic()-started}


def copy_archive(source: Path, destination: Path) -> Path:
    """Publish a byte-verified weekly copy of the already verified daily archive."""
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if source == destination:
        raise ValueError('Archive source and destination must differ')
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True)
    require_space(parent, source.stat().st_size + CHUNK)
    with tempfile.TemporaryDirectory(prefix='.snapshot-', dir=parent) as directory:
        temporary = Path(directory).resolve()
        if temporary.parent != parent:
            raise ValueError('Temporary path escaped destination directory')
        copied = temporary / 'weekly.partial'
        with source.open('rb') as src, copied.open('xb') as dst:
            original = hashlib.sha256()
            for chunk in iter(lambda: src.read(CHUNK), b''):
                require_space(parent, 0)
                original.update(chunk); dst.write(chunk)
            dst.flush(); os.fsync(dst.fileno())
        with copied.open('rb') as stream:
            if digest_stream(stream) != original.hexdigest():
                raise ValueError('Weekly archive checksum mismatch')
        os.replace(copied, destination)
        _sync_directory(parent)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--source', type=Path)
    inputs.add_argument('--copy-archive', type=Path)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    # Only the final pathname goes to stdout, for the cron shell wrapper.
    if args.copy_archive:
        print(copy_archive(args.copy_archive, args.destination))
    else:
        print(create_snapshot(args.source, args.destination)['path'])

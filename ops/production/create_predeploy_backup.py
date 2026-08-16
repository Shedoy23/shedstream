"""Create a consistent SQLite pre-deploy backup and verify it before compression."""

from __future__ import annotations

import argparse
import pathlib
import sqlite3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    database = pathlib.Path(args.database).resolve()
    output = pathlib.Path(args.output).resolve()
    if not database.is_file():
        raise SystemExit("source database is missing")
    if output.exists():
        raise SystemExit("backup output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(output)
    try:
        source.backup(destination)
        result = destination.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"backup quick_check failed: {result}")
        destination.commit()
    except Exception:
        destination.close()
        source.close()
        output.unlink(missing_ok=True)
        raise
    destination.close()
    source.close()
    print(f"BACKUP_OK path={output} size={output.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

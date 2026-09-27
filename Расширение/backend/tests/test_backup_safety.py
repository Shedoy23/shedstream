"""Standalone regression tests; all writes stay in a disposable test directory."""
import asyncio
import gzip
import hashlib
import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import backup_loop


class BackupSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='backup-safety-')
        self.root = Path(self.temp.name)
        self.src = self.root / 'live.db'
        with sqlite3.connect(self.src) as c:
            c.execute('CREATE TABLE money(id INTEGER PRIMARY KEY, balance INTEGER)')
            c.execute('INSERT INTO money VALUES (1,700)')

    def tearDown(self):
        self.temp.cleanup()

    def test_backup_is_compressed_and_restorable(self):
        result = backup_loop._do_backup_sync(self.src, self.root / 'backup_new.db')
        self.assertTrue(result['success'], result)
        path = Path(result.get('path', str(self.root / 'backup_new.db')))
        self.assertIn(path.suffix, ['.gz', '.zst'])
        if path.suffix == '.gz':
            raw = gzip.decompress(path.read_bytes())
        else:
            import subprocess
            raw = subprocess.check_output(['zstd', '-q', '-d', '-c', str(path)])
        restored = self.root / 'restored.db'
        restored.write_bytes(raw)
        with sqlite3.connect(restored) as c:
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone(), ('ok',))
            self.assertEqual(c.execute('SELECT balance FROM money').fetchone(), (700,))

    def test_missing_source_is_not_created(self):
        missing = self.root / 'missing.db'
        result = backup_loop._do_backup_sync(missing, self.root / 'backup_missing.db')
        self.assertFalse(result['success'])
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.root.glob('backup_missing*')), [])

    def test_unknown_disk_space_fails_closed(self):
        with mock.patch.object(backup_loop.shutil, 'disk_usage', side_effect=OSError('disk unavailable')):
            self.assertEqual(backup_loop._free_disk_mb(self.root), 0)

    def test_pruning_counts_old_and_compressed_snapshots_together(self):
        names = ['backup_1.db', 'backup_2.db.gz', 'backup_3.db.zst']
        for n, name in enumerate(names):
            p = self.root / name; p.write_bytes(b'fixture'); os.utime(p, (100+n, 100+n))
        foreign = self.root / 'viewer.db'; foreign.write_bytes(b'keep')
        partial = self.root / '.backup-incomplete'; partial.write_bytes(b'keep')
        self.assertEqual(backup_loop._prune_old(self.root, 2), 1)
        self.assertFalse((self.root / names[0]).exists())
        self.assertTrue((self.root / names[1]).exists())
        self.assertTrue((self.root / names[2]).exists())
        self.assertTrue(foreign.exists()); self.assertTrue(partial.exists())

    def test_invalid_retention_never_removes_last_snapshot(self):
        p = self.root / 'backup_1.db'; p.write_bytes(b'last')
        backup_loop._prune_old(self.root, 0)
        self.assertTrue(p.exists())

    def test_daily_uses_fast_compression(self):
        shell = (BACKEND / 'backup_db.sh').read_text(encoding='utf-8')
        self.assertNotIn('zstd -q -19', shell)


if __name__ == '__main__':
    unittest.main(verbosity=2)

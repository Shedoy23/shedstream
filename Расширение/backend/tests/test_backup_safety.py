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
from contextlib import closing

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import backup_loop
try:
    import backup_storage
except ImportError:
    backup_storage = None


class BackupSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='backup-safety-', dir=Path.cwd())
        self.root = Path(self.temp.name)
        self.src = self.root / 'live.db'
        with closing(sqlite3.connect(self.src)) as c:
            c.execute('CREATE TABLE money(id INTEGER PRIMARY KEY, balance INTEGER)')
            c.execute('INSERT INTO money VALUES (1,700)')
            c.commit()

    def tearDown(self):
        assert self.root.resolve().parent == Path.cwd().resolve()
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
        with closing(sqlite3.connect(restored)) as c:
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

    def test_wal_commits_are_in_the_snapshot(self):
        with closing(sqlite3.connect(self.src)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('UPDATE money SET balance=901'); writer.commit()
            with mock.patch.object(backup_storage.shutil, 'which', return_value=None):
                result = backup_loop._do_backup_sync(self.src, self.root / 'backup_wal.db')
            self.assertTrue(result['success'], result)
            restored = self.root / 'wal-restored.db'
            restored.write_bytes(gzip.decompress(Path(result['path']).read_bytes()))
            with closing(sqlite3.connect(restored)) as db:
                self.assertEqual(db.execute('SELECT balance FROM money').fetchone(), (901,))

    def test_nonempty_compression_failure_is_cleaned_and_old_backup_survives(self):
        old = self.root / 'backup_old.db.gz'; old.write_bytes(b'previous-good-backup')
        def broken(raw, target, zstd):
            target.write_bytes(b'partial-nonzero'); raise OSError('disk full')
        with mock.patch.object(backup_storage, '_compress', side_effect=broken):
            result = backup_loop._do_backup_sync(self.src, self.root / 'backup_old.db')
        self.assertFalse(result['success'])
        self.assertEqual(old.read_bytes(), b'previous-good-backup')
        self.assertEqual(list(self.root.glob('.snapshot-*')), [])

    def test_bad_decompression_digest_never_publishes(self):
        with mock.patch.object(backup_storage, '_archive_digest', return_value='wrong'):
            result = backup_loop._do_backup_sync(self.src, self.root / 'backup_bad.db')
        self.assertFalse(result['success'])
        self.assertEqual(list(self.root.glob('backup_bad*')), [])
        self.assertEqual(list(self.root.glob('.snapshot-*')), [])

    def test_publish_failure_preserves_existing_backup(self):
        old = self.root / 'backup_old.db.gz'; old.write_bytes(b'previous-good-backup')
        with mock.patch.object(backup_storage.os, 'replace', side_effect=PermissionError('denied')):
            result = backup_loop._do_backup_sync(self.src, self.root / 'backup_old.db')
        self.assertFalse(result['success'])
        self.assertEqual(old.read_bytes(), b'previous-good-backup')
        self.assertEqual(list(self.root.glob('.snapshot-*')), [])

    def test_space_budget_includes_database_and_reserve(self):
        usage = __import__('collections').namedtuple('Usage', 'total used free')
        with mock.patch.object(backup_storage.shutil, 'disk_usage',
                               return_value=usage(10**9, 0, backup_storage.RESERVE_BYTES + 100)):
            result = backup_loop._do_backup_sync(self.src, self.root / 'backup_full.db')
        self.assertFalse(result['success'])
        self.assertEqual(list(self.root.glob('backup_full*')), [])

    def test_unreadable_disk_usage_does_not_start_copy(self):
        with mock.patch.object(backup_storage.shutil, 'disk_usage', side_effect=OSError('unknown')):
            result = backup_loop._do_backup_sync(self.src, self.root / 'backup_unknown.db')
        self.assertFalse(result['success'])
        self.assertEqual(list(self.root.glob('.snapshot-*')), [])

    def test_corrupt_source_does_not_replace_previous_copy(self):
        corrupt = self.root / 'corrupt.db'; corrupt.write_bytes(b'not SQLite')
        old = self.root / 'backup_old.db.gz'; old.write_bytes(b'previous-good-backup')
        result = backup_loop._do_backup_sync(corrupt, self.root / 'backup_old.db')
        self.assertFalse(result['success'])
        self.assertEqual(old.read_bytes(), b'previous-good-backup')

    def test_empty_database_rejected(self):
        empty = self.root / 'empty.db'
        with closing(sqlite3.connect(empty)):
            pass
        result = backup_loop._do_backup_sync(empty, self.root / 'backup_empty.db')
        self.assertFalse(result['success'])

    def test_failure_does_not_trigger_prune(self):
        sleeps = 0
        async def stop_after_iteration(seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                raise asyncio.CancelledError()
        with mock.patch.object(backup_loop, '_resolve_db_path', return_value=self.src), \
             mock.patch.object(backup_loop, '_resolve_backup_dir', return_value=self.root), \
             mock.patch.object(backup_loop.asyncio, 'sleep', side_effect=stop_after_iteration), \
             mock.patch.object(backup_loop, '_do_backup_sync', return_value={'success':False,'error':'test'}), \
             mock.patch.object(backup_loop, '_prune_old') as prune:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(backup_loop.db_backup_loop())
            prune.assert_not_called()

    def test_weekly_copy_verifies_bytes_and_cleans_partial(self):
        source = self.root / 'daily.db.gz'
        source.write_bytes(gzip.compress(b'validated daily content'))
        destination = self.root / 'weekly.gz'
        backup_storage.copy_archive(source, destination)
        self.assertEqual(source.read_bytes(), destination.read_bytes())
        with mock.patch.object(backup_storage, 'digest_stream', return_value='mismatch'):
            with self.assertRaises(ValueError):
                backup_storage.copy_archive(source, destination)
        self.assertEqual(source.read_bytes(), destination.read_bytes())
        self.assertEqual(list(self.root.glob('.snapshot-*')), [])

    def test_zstd_uses_level_three_and_compressor_errors_propagate(self):
        target = self.root / 'compress.partial'
        with mock.patch.object(backup_storage.subprocess, 'run', side_effect=OSError('zstd failed')) as run:
            with self.assertRaises(OSError):
                backup_storage._compress(self.src, target, '/usr/bin/zstd')
            self.assertEqual(run.call_args.args[0], ['/usr/bin/zstd','-q','-3','-c',str(self.src)])

    def test_directory_sync_failure_prevents_retention(self):
        with mock.patch.object(backup_storage, '_sync_directory', side_effect=OSError('fsync failed')):
            result = backup_loop._do_backup_sync(self.src, self.root / 'backup_sync.db')
        self.assertFalse(result['success'])
        # A complete archive may be visible, but a failed result cannot prune old ones.


class RetentionAudit(unittest.TestCase):
    def test_inventory_is_read_only_and_keeps_financial_and_dedup_holds(self):
        from datetime import datetime, timezone
        from retention_audit import audit
        with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='retention-test-') as directory:
            root = Path(directory).resolve(); assert root.parent == Path.cwd().resolve()
            path = root / 'db.sqlite'
            with closing(sqlite3.connect(path)) as c:
                c.executescript("""
                CREATE TABLE module_actions(action_id TEXT,channel_id INTEGER,module_id TEXT,status TEXT,client_action_id TEXT,created_at TEXT,data TEXT,error_msg TEXT);
                INSERT INTO module_actions VALUES('old',1,'bannerlord','failed','dedup','2026-01-01','{}',NULL);
                INSERT INTO module_actions VALUES('pending',2,'bannerlord','dispatched',NULL,'2026-01-01','{}',NULL);
                CREATE TABLE requests(channel_id INTEGER,action_id TEXT);
                INSERT INTO requests VALUES(1,'old');
                CREATE TABLE bannerlord_events_log(channel_id INTEGER,created_at TEXT);
                INSERT INTO bannerlord_events_log VALUES(1,'2026-01-01');
                CREATE TABLE points_ledger(balance INTEGER);
                INSERT INTO points_ledger VALUES(700);
                """)
                c.commit()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            report = audit(path, datetime(2026,9,27,tzinfo=timezone.utc))
            self.assertFalse(report['delete_authorized_by_this_report'])
            self.assertEqual(report['snapshot_last_action_by_channel'], {1: '2026-01-01', 2: '2026-01-01'})
            self.assertEqual(report['aged_client_id_keys'], 1)
            self.assertEqual(report['references_to_aged_actions'], [{'table':'requests','count':1}])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)

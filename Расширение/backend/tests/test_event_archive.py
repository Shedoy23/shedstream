"""Standalone tests: real SQLite transactions; never a production database."""
from contextlib import closing
from datetime import datetime, timezone
import gzip, json, sqlite3, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import event_archive as ea

NOW = datetime(2026,9,27,tzinfo=timezone.utc)
SCHEMA = '''CREATE TABLE bannerlord_events_log (
 id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER NOT NULL,
 event_type TEXT NOT NULL, username TEXT, payload TEXT,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
 CREATE INDEX idx_events ON bannerlord_events_log(channel_id,created_at);
 CREATE TABLE module_actions(id INTEGER PRIMARY KEY,client_action_id TEXT);
 INSERT INTO module_actions VALUES(1,'dedup-preserve');
 CREATE TABLE points_ledger(id INTEGER PRIMARY KEY,amount INTEGER);
 INSERT INTO points_ledger VALUES(1,777);
 CREATE TABLE viewers(id INTEGER PRIMARY KEY,balance INTEGER);
 INSERT INTO viewers VALUES(1,777);
 CREATE TABLE activity_stats(channel_id INTEGER,minutes INTEGER);
 INSERT INTO activity_stats VALUES(11,555);'''

class EventArchive(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path.cwd(),prefix='event-test-')
        self.root=Path(self.temp.name); self.db=self.root/'live.db'; self.dest=self.root/'archives'
        with closing(sqlite3.connect(self.db)) as c:
            c.executescript(SCHEMA)
            c.executemany('INSERT INTO bannerlord_events_log VALUES(?,?,?,?,?,?)',[
                (1,11,'hero.sync','зритель','{"x":"строка\\n"}','2026-08-01 00:00:00'),
                (2,11,'hero.sync',None,None,'2026-08-27 23:59:59'),
                (3,11,'battle',None,'{}','2026-08-28 00:00:00'),
                (4,22,'hero.sync','other','{}','2026-08-01 00:00:00'),
                (5,11,'battle','alice','{}','2026-09-26 00:00:00')])
            c.commit()
        self.before=self.rows(); self.protected=self.others()
    def tearDown(self):
        assert self.root.resolve().parent==Path.cwd().resolve()
        self.temp.cleanup()
    def sql(self,s,args=()):
        with closing(sqlite3.connect(self.db)) as c:
            rows=c.execute(s,args).fetchall(); c.commit(); return rows
    def rows(self): return self.sql('SELECT * FROM bannerlord_events_log ORDER BY id')
    def others(self):return {t:self.sql('SELECT * FROM '+t) for t in ['viewers','module_actions','points_ledger','activity_stats']}
    def archive(self,**kw):return ea.archive(self.db,self.dest,11,as_of=NOW,**kw)
    def test_archive_is_read_only_and_verified(self):
        a=self.archive(); self.assertEqual(self.rows(),self.before)
        m,rows=ea.verify(a);self.assertEqual([r[0] for r in rows],[1,2]);self.assertEqual(m['count'],2)
        self.assertEqual(self.others(),self.protected)
    def test_prune_restore_and_idempotence(self):
        a=self.archive();self.assertEqual(ea.prune(self.db,a)['deleted'],2)
        self.assertEqual([r[0] for r in self.rows()],[3,4,5])
        self.assertEqual(ea.prune(self.db,a)['deleted'],0)
        self.assertEqual(ea.restore(self.db,a)['restored'],2)
        self.assertEqual(ea.restore(self.db,a)['restored'],0)
        self.assertEqual(self.rows(),self.before);self.assertEqual(self.others(),self.protected)
    def test_batch_is_bounded(self):
        a=self.archive(batch_size=1);self.assertEqual(ea.verify(a)[0]['count'],1)
        ea.prune(self.db,a);b=self.archive(batch_size=1)
        self.assertNotEqual(a,b);ea.prune(self.db,b)
        self.assertEqual([r[0] for r in self.rows()],[3,4,5])
    def test_new_rows_between_archive_and_prune_survive(self):
        a=self.archive();self.sql("INSERT INTO bannerlord_events_log(channel_id,event_type,created_at) VALUES(11,'late','2026-08-01 00:00:00')")
        ea.prune(self.db,a);self.assertEqual([r[0] for r in self.rows()],[3,4,5,6])
    def test_changed_archived_row_aborts_whole_transaction(self):
        a=self.archive();self.sql("UPDATE bannerlord_events_log SET payload='changed' WHERE id=2")
        before=self.rows()
        with self.assertRaises(ValueError):ea.prune(self.db,a)
        self.assertEqual(self.rows(),before)
    def test_corrupt_archive_never_deletes(self):
        a=self.archive();p=a/'events.jsonl.gz';p.write_bytes(p.read_bytes()[:-8])
        with self.assertRaises((ValueError,EOFError,OSError)):ea.prune(self.db,a)
        self.assertEqual(self.rows(),self.before)
    def test_changed_manifest_never_deletes(self):
        a=self.archive();p=a/'manifest.json';m=json.loads(p.read_text());m['channel_id']=22;p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):ea.prune(self.db,a)
        self.assertEqual(self.rows(),self.before)
    def test_repacked_corruption_fails_checksum(self):
        a=self.archive();p=a/'events.jsonl.gz'
        raw=gzip.decompress(p.read_bytes()).replace(b'hero.sync',b'hero.sinc',1)
        p.write_bytes(gzip.compress(raw))
        with self.assertRaises(ValueError):ea.verify(a)
        self.assertEqual(self.rows(),self.before)
    def test_wrong_database_path_rejected(self):
        a=self.archive();other=self.root/'other.db';other.write_bytes(self.db.read_bytes())
        with self.assertRaises(ValueError):ea.prune(other,a)
    def test_restore_conflict_is_atomic(self):
        a=self.archive();ea.prune(self.db,a)
        self.sql("INSERT INTO bannerlord_events_log VALUES(2,11,'conflict',NULL,NULL,'2026-09-26 00:00:00')")
        before=self.rows()
        with self.assertRaises(ValueError):ea.restore(self.db,a)
        self.assertEqual(self.rows(),before)
    def test_schema_drift_rejected(self):
        a=self.archive();self.sql('ALTER TABLE bannerlord_events_log ADD COLUMN future TEXT')
        with self.assertRaises(ValueError):ea.prune(self.db,a)
        self.assertEqual(len(self.rows()),5)
    def test_trigger_blocks_prune(self):
        a=self.archive();self.sql('CREATE TRIGGER surprise AFTER DELETE ON bannerlord_events_log BEGIN UPDATE viewers SET balance=0; END')
        with self.assertRaises(ValueError):ea.prune(self.db,a)
        self.assertEqual(self.others(),self.protected);self.assertEqual(self.rows(),self.before)
    def test_incoming_foreign_key_blocks_prune(self):
        a=self.archive();self.sql('CREATE TABLE child(event_id INTEGER REFERENCES bannerlord_events_log(id) ON DELETE CASCADE)')
        with self.assertRaises(ValueError):ea.prune(self.db,a)
        self.assertEqual(self.rows(),self.before)
    def test_wrong_timestamp_is_not_pruned(self):
        self.sql("UPDATE bannerlord_events_log SET created_at='2026-01-bad' WHERE id=1")
        with self.assertRaises(ValueError):self.archive()
        self.assertEqual(len(self.rows()),5)
    def test_no_archive_for_no_eligible_rows(self):
        self.assertIsNone(ea.archive(self.db,self.dest,33,as_of=NOW))
        self.assertEqual(self.rows(),self.before)
    def test_low_disk_never_publishes_or_deletes(self):
        with patch.object(ea,'require_space',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.archive()
        self.assertEqual(self.rows(),self.before)
        self.assertFalse(list(self.dest.glob('events-*')))
    def test_fsync_failure_leaves_no_published_archive(self):
        with patch.object(ea.os,'fsync',side_effect=OSError('fsync failed')):
            with self.assertRaises(OSError):self.archive()
        self.assertEqual(self.rows(),self.before)
        self.assertFalse(list(self.dest.glob('events-*')))
    def test_prune_failure_rolls_back_first_delete(self):
        a=self.archive()
        with patch.object(ea,'_delete_rows',side_effect=self.fail_delete):
            with self.assertRaises(RuntimeError):ea.prune(self.db,a)
        self.assertEqual(self.rows(),self.before)
    @staticmethod
    def fail_delete(c,rows):
        c.execute('DELETE FROM bannerlord_events_log WHERE id=? AND channel_id=?',rows[0][:2])
        raise RuntimeError('simulated interruption')
    def test_retain_30_days_minimum(self):
        with self.assertRaises(ValueError):self.archive(retain_days=29)
        with self.assertRaises(ValueError):self.archive(batch_size=10001)
    def test_naive_and_future_clock_rejected(self):
        for instant in [datetime(2026,9,27),datetime(2099,1,1,tzinfo=timezone.utc)]:
            with self.assertRaises(ValueError):ea.archive(self.db,self.dest,11,as_of=instant)
    def test_missing_database_not_created(self):
        missing=self.root/'missing.db'
        with self.assertRaises((FileNotFoundError,sqlite3.OperationalError)):ea.archive(missing,self.dest,11,as_of=NOW)
        self.assertFalse(missing.exists())
    def test_delete_highest_id_does_not_reuse_it(self):
        self.sql("UPDATE bannerlord_events_log SET created_at='2026-08-01 00:00:00' WHERE id=5")
        a=self.archive();ea.prune(self.db,a)
        self.sql("INSERT INTO bannerlord_events_log(channel_id,event_type) VALUES(11,'new')")
        self.assertEqual(self.sql('SELECT MAX(id) FROM bannerlord_events_log'),[(6,)])

if __name__=='__main__':unittest.main(verbosity=2)

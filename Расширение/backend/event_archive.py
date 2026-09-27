"""Offline operator CLI: archive Bannerlord audit events, then prune exact rows.

No scheduler, startup hook, VACUUM, action/ledger changes or archive expiry.
Archive first; copy the verified directory off-host before production prune.
"""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid

TABLE = 'bannerlord_events_log'
COLS = ('id','channel_id','event_type','username','payload','created_at')
FIELDS = ','.join(COLS)
MAX_ROWS = 10_000
MAX_BYTES = 64 * 1024 * 1024
RESERVE = 200 * 1024 * 1024


def require_space(directory: Path, extra: int = MAX_BYTES) -> None:
    if shutil.disk_usage(directory).free < RESERVE + extra:
        raise OSError('Insufficient free space for safe event retention')


def _sync_dir(p: Path) -> None:
    if os.name != 'nt':
        fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def _open(path: Path, write: bool = False) -> sqlite3.Connection:
    path = Path(path).resolve(strict=True)
    c = sqlite3.connect(path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=3)
    c.execute('PRAGMA foreign_keys=ON')
    if not write: c.execute('PRAGMA query_only=ON')
    else: c.execute('PRAGMA synchronous=FULL')
    return c


def _schema(c: sqlite3.Connection) -> list:
    info = c.execute('PRAGMA table_info('+TABLE+')').fetchall()
    shape = [(r[1],r[2].upper(),r[3],r[5]) for r in info]
    expected = [('id','INTEGER',0,1),('channel_id','INTEGER',1,0),
                ('event_type','TEXT',1,0),('username','TEXT',0,0),
                ('payload','TEXT',0,0),('created_at','TIMESTAMP',1,0)]
    sql = c.execute('SELECT sql FROM sqlite_master WHERE type=? AND name=?',('table',TABLE)).fetchone()
    if shape != expected or not sql or 'AUTOINCREMENT' not in sql[0].upper():
        raise ValueError('Unexpected events schema; inspect before retention')
    if c.execute('SELECT 1 FROM sqlite_master WHERE type=? AND tbl_name=?',('trigger',TABLE)).fetchone():
        raise ValueError('Event table triggers need explicit review')
    if c.execute('PRAGMA foreign_key_list('+TABLE+')').fetchall():
        raise ValueError('Event table foreign keys need explicit review')
    for (table,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        quoted = '"'+table.replace('"','""')+'"'
        if any(r[2].lower()==TABLE for r in c.execute('PRAGMA foreign_key_list('+quoted+')')):
            raise ValueError('Incoming event foreign key needs explicit review')
    return [list(r) for r in info]


def _cutoff(as_of: datetime, retain_days: int) -> str:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('Use an explicit UTC/timezone-aware timestamp')
    if as_of > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError('Future as-of timestamp refused')
    if type(retain_days) is not int or retain_days < 30:
        raise ValueError('Keep at least 30 days of live events')
    return (as_of.astimezone(timezone.utc)-timedelta(days=retain_days)).strftime('%Y-%m-%d %H:%M:%S')


def _row(row: list | tuple, channel_id: int, cutoff: str) -> None:
    if len(row)!=6 or type(row[0]) is not int or row[0]<=0 or type(row[1]) is not int or row[1]!=channel_id:
        raise ValueError('Invalid event identity or channel')
    if not isinstance(row[2],str) or any(x is not None and not isinstance(x,str) for x in row[3:5]):
        raise ValueError('Unexpected event field types')
    if not isinstance(row[5],str): raise ValueError('Missing timestamp')
    instant = datetime.strptime(row[5],'%Y-%m-%d %H:%M:%S')
    if instant.strftime('%Y-%m-%d %H:%M:%S')!=row[5] or row[5]>=cutoff:
        raise ValueError('Noncanonical or recent event timestamp')


def archive(db: Path, destination: Path, channel_id: int, *, as_of: datetime | None = None,
            retain_days: int = 30, batch_size: int = 2000) -> Path | None:
    """Read-only snapshot of <=batch_size old events; return verified directory."""
    db = Path(db).resolve(strict=True)
    as_of = as_of or datetime.now(timezone.utc)
    cutoff = _cutoff(as_of,retain_days)
    if type(channel_id) is not int or channel_id<=0 or type(batch_size) is not int or not 1<=batch_size<=MAX_ROWS:
        raise ValueError('Positive channel and batch size 1..10000 required')
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    require_space(destination)
    with closing(_open(db)) as c:
        c.execute('BEGIN')
        schema = _schema(c)
        # The existing (channel_id,created_at) index bounds this operation.
        cursor = c.execute('SELECT '+FIELDS+' FROM '+TABLE+' WHERE channel_id=? AND created_at<? ORDER BY created_at,id LIMIT ?',
                           (channel_id,cutoff,batch_size))
        first = cursor.fetchone()
        if first is None: return None
        with tempfile.TemporaryDirectory(prefix='.events-',dir=destination) as td:
            temp = Path(td).resolve()
            if temp.parent != destination: raise ValueError('Temporary directory escaped archive root')
            # Publish a subdirectory; TemporaryDirectory keeps its original path.
            ready = temp/'ready'; ready.mkdir(mode=0o700)
            digest = hashlib.sha256(); count = size = 0
            with (ready/'events.jsonl.gz').open('xb') as raw:
                with gzip.GzipFile(filename='',fileobj=raw,mode='wb',compresslevel=1,mtime=0) as packed:
                    row = first
                    while row is not None:
                        _row(row,channel_id,cutoff)
                        line = (json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf-8')
                        size += len(line)
                        if size>MAX_BYTES: raise ValueError('Batch exceeds 64 MiB; lower batch size')
                        require_space(destination,0)
                        packed.write(line); digest.update(line); count += 1
                        row = cursor.fetchone()
                raw.flush(); os.fsync(raw.fileno())
            meta = {'version':1,'table':TABLE,'source_path':str(db),'channel_id':channel_id,
                    'as_of':as_of.isoformat(),'retain_days':retain_days,'cutoff':cutoff,
                    'schema':schema,'count':count,'raw_bytes':size,'sha256':digest.hexdigest()}
            with (ready/'manifest.json').open('x',encoding='utf-8') as f:
                json.dump(meta,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
            verify(ready)  # Full decode, SHA, schema/row metadata and count before publication.
            _sync_dir(ready)
            final = destination/('events-'+str(channel_id)+'-'+uuid.uuid4().hex)
            os.rename(ready,final)
            _sync_dir(destination)
            return final


def verify(directory: Path) -> tuple[dict,list[tuple]]:
    directory = Path(directory).resolve(strict=True)
    meta = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if meta.get('version')!=1 or meta.get('table')!=TABLE or type(meta.get('channel_id')) is not int or meta['channel_id']<=0:
        raise ValueError('Unknown archive format or channel')
    cutoff = _cutoff(datetime.fromisoformat(meta['as_of']),meta['retain_days'])
    if cutoff!=meta['cutoff'] or not 1<=meta['count']<=MAX_ROWS or not 1<=meta['raw_bytes']<=MAX_BYTES:
        raise ValueError('Invalid archive bounds')
    digest=hashlib.sha256(); size=0; rows=[]; ids=set()
    with gzip.open(directory/'events.jsonl.gz','rb') as stream:
        while True:
            line=stream.readline(MAX_BYTES+1)
            if not line: break
            size+=len(line)
            if size>MAX_BYTES or len(rows)>=MAX_ROWS: raise ValueError('Archive exceeds bounds')
            digest.update(line)
            row=json.loads(line)
            _row(row,meta['channel_id'],cutoff)
            if row[0] in ids: raise ValueError('Duplicate event identity in archive')
            ids.add(row[0]); rows.append(tuple(row))
    if size!=meta['raw_bytes'] or len(rows)!=meta['count'] or digest.hexdigest()!=meta['sha256']:
        raise ValueError('Archive checksum or count mismatch')
    return meta,rows


def _delete_rows(c: sqlite3.Connection, rows: list[tuple]) -> None:
    # tenant-ok: every deletion includes explicit archived channel_id.
    c.executemany('DELETE FROM '+TABLE+' WHERE id=? AND channel_id=?',[(r[0],r[1]) for r in rows])


def _change(db: Path, directory: Path, restoring: bool) -> dict:
    db=Path(db).resolve(strict=True)
    meta,rows=verify(directory)  # Corruption fails before a writable DB is opened.
    if not restoring and str(db)!=meta['source_path']:
        raise ValueError('Archive belongs to a different source path')
    require_space(db.parent)
    with closing(_open(db,True)) as c:
        try:
            c.execute('BEGIN IMMEDIATE')
            if _schema(c)!=meta['schema']: raise ValueError('Schema changed since archival')
            present=[]; missing=[]
            for row in rows:
                # Global PK lookup catches ID collision across channels on restore.
                actual=c.execute('SELECT '+FIELDS+' FROM '+TABLE+' WHERE id=?',(row[0],)).fetchone()
                if actual is None: missing.append(row)
                elif actual==row: present.append(row)
                else: raise ValueError('Archived event differs from current row; no changes applied')
            if restoring:
                # tenant-ok: full archived rows include their validated channel_id.
                c.executemany('INSERT INTO '+TABLE+' ('+FIELDS+') VALUES (?,?,?,?,?,?)',missing)
            else:
                _delete_rows(c,present)
            c.commit()
        except BaseException:
            c.rollback(); raise
    return {('restored' if restoring else 'deleted'):len(missing if restoring else present),
            'archive':str(Path(directory).resolve()),'channel_id':meta['channel_id']}


def prune(db: Path, directory: Path) -> dict:
    """Prune only already-archived exact rows; repeated calls are safe."""
    return _change(db,directory,False)


def restore(db: Path, directory: Path) -> dict:
    """Restore missing events; refuse conflicting IDs, preserve all newer data."""
    return _change(db,directory,True)


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('archive')
    p.add_argument('--db',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--channel-id',type=int,required=True)
    p.add_argument('--retain-days',type=int,default=30);p.add_argument('--batch-size',type=int,default=2000)
    p.add_argument('--as-of',type=datetime.fromisoformat)
    for command in ['verify','prune','restore']:
        p=sub.add_parser(command);p.add_argument('--archive',type=Path,required=True)
        if command!='verify':p.add_argument('--db',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='archive':
        result=archive(args.db,args.out,args.channel_id,as_of=args.as_of,retain_days=args.retain_days,batch_size=args.batch_size)
        print(json.dumps({'archive':str(result) if result else None}))
    elif args.command=='verify':
        meta,_=verify(args.archive)
        print(json.dumps({k:meta[k] for k in ['count','channel_id','cutoff','sha256']}))
    else:
        print(json.dumps((prune if args.command=='prune' else restore)(args.db,args.archive)))


if __name__=='__main__':main()

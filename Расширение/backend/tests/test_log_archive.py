"""Application audit survives stdout rotation; archives are compressed and bounded."""
import gzip
import logging
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logging_setup import create_archive_handler

with tempfile.TemporaryDirectory() as tmp:
    handler = create_archive_handler(tmp, days=2)
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.emit(logging.makeLogRecord({'msg': 'paid action audit survives'}))
    handler.doRollover()
    archives = list(Path(tmp).glob('*.gz'))
    assert len(archives) == 1
    assert 'paid action audit survives' in gzip.open(archives[0], 'rt').read()
    for date in ('2001-01-01','2001-01-02','2001-01-03'):
        (Path(tmp) / ('application.log.' + date + '.gz')).write_bytes(b'old')
    handler.rolloverAt += 86400
    handler.doRollover()
    handler.close()
    assert len(list(Path(tmp).glob('*.gz'))) <= 2
print('PASS compressed application archive and retention')

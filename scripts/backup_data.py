"""Read-only source backup. No application imports, migrations or Gemini access.
Run while uploads, settings edits, OCR and deletions are paused. SQLite backup
provides a consistent database snapshot; hash checks reject changing assets.
"""
import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination.exists():
        raise ValueError('Use a new backup directory outside the source root.')
    files = sorted(p for folder in ('books','config','exports','logs') for p in (source/folder).rglob('*') if p.is_file())
    before = {str(p.relative_to(source)): digest(p) for p in files}
    destination.mkdir(parents=True)
    # Leave any failed backup in place for inspection, never remove source files.
    for p in files:
        target = destination/p.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    db_path = destination/'data/library.db'
    db_path.parent.mkdir()
    with sqlite3.connect((source/'data/library.db').as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(db_path) as dst: src.backup(dst)
    with sqlite3.connect(db_path.as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]: raise RuntimeError('Backup integrity check failed')
        counts = dict(db.execute('SELECT status,count(*) FROM book_pages GROUP BY status'))
        for stored, original in db.execute('SELECT stored_filename,file_path FROM books'):
            original = Path(original)
            relative = original.resolve().relative_to(source)
            if not (destination/relative).is_file(): raise RuntimeError('A referenced PDF is missing from backup')
    after_files = sorted(p for folder in ('books','config','exports','logs') for p in (source/folder).rglob('*') if p.is_file())
    after = {str(p.relative_to(source)): digest(p) for p in after_files}
    if before != after: raise RuntimeError('Source assets changed; pause edits and retry to a new destination')
    if any(digest(destination/name) != value for name,value in before.items()): raise RuntimeError('Copied asset hash mismatch')
    manifest = {'source':str(source),'database_integrity':'ok','page_counts':counts,'sha256':{**before,'data/library.db':digest(db_path)},'note':'SQLite snapshot; original absolute PDF paths retained. Never launch backup directly.'}
    (destination/'verified-backup.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return counts


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('destination')
    args=parser.parse_args()
    print('Verified backup page counts:',backup(args.source,args.destination))

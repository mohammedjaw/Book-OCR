from threading import Lock, Event, Thread
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from .database import connect
from .ocr_service import extract_page
_jobs={}; _lock=Lock()
def recover_stale():
    cutoff=(datetime.now()-timedelta(minutes=30)).isoformat(timespec='seconds')
    with connect() as db: db.execute("UPDATE book_pages SET status='pending',error_message=NULL,updated_at=? WHERE status='processing' AND updated_at < ?",(datetime.now().isoformat(timespec='seconds'),cutoff))
def _run(book_id,retry_failed=False):
    try:
        with connect() as db:
            states=('failed',) if retry_failed else ('pending','failed')
            pages=[r['page_number'] for r in db.execute("SELECT page_number FROM book_pages WHERE book_id=? AND status IN (?,?) ORDER BY page_number",(book_id,states[0],states[1]))]
            setting=db.execute("SELECT value FROM settings WHERE key='max_concurrent_pages'").fetchone()
        limit=max(1,min(5,int(setting[0]) if setting else 3)); next_page=0; futures={}
        with ThreadPoolExecutor(max_workers=limit) as pool:
            while True:
                with _lock: paused=not _jobs.get(book_id) or _jobs[book_id]['pause'].is_set()
                while not paused and len(futures)<limit and next_page<len(pages):
                    page=pages[next_page]; next_page+=1
                    futures[pool.submit(extract_page,book_id,page)]=page
                if not futures: break
                done,not_done=wait(futures,return_when=FIRST_COMPLETED)
                for future in done:
                    futures.pop(future)
                    try: future.result()
                    except Exception: pass
    finally:
        with _lock: _jobs.pop(book_id,None)
def start(book_id,retry_failed=False):
    with _lock:
        if book_id in _jobs:return False
        _jobs[book_id]={'pause':Event()}; Thread(target=_run,args=(book_id,retry_failed),daemon=True).start(); return True
def pause(book_id):
    with _lock:
        if book_id in _jobs:_jobs[book_id]['pause'].set(); return True
    return False
def active(book_id):
    with _lock:return book_id in _jobs

from threading import RLock, Event, Thread
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
from .database import connect
from .ocr_service import extract_page
from .gemini_key_manager import KeysUnavailable, SchedulingPaused

_jobs = {}
_lock = RLock()
RETRYABLE = "(error_kind IS NULL OR error_kind IN ('network_error','service_error','rate_limited','application_error','page_service_failure'))"

def recover_stale():
    # Startup only, before accepting requests. All prior process claims are stale.
    with connect() as db:
        db.execute("UPDATE book_pages SET status='pending',error_message=NULL,error_kind=NULL,updated_at=? WHERE status='processing'", (datetime.now().isoformat(),))
        db.execute("UPDATE books SET status='paused' WHERE status IN ('running','pausing')")

def _run(book_id, job, retry_failed=False, page_number=None, rerender_failed=False):
    reason = None
    retry_pages = None
    try:
        with connect() as db:
            if retry_failed:
                retry_pages = {r[0] for r in db.execute(f"SELECT page_number FROM book_pages WHERE book_id=? AND status='failed' AND {RETRYABLE}",(book_id,))}
                db.execute(f"UPDATE book_pages SET status='pending',error_message=NULL,error_kind=NULL WHERE book_id=? AND status='failed' AND {RETRYABLE}", (book_id,))
            elif rerender_failed:
                retry_pages = {page_number}
                reset = db.execute("UPDATE book_pages SET status='pending',error_message=NULL,error_kind=NULL,updated_at=? WHERE book_id=? AND page_number=? AND status='failed'", (datetime.now().isoformat(), book_id, page_number)).rowcount
                if not reset:
                    return
            setting = db.execute("SELECT value FROM settings WHERE key='max_concurrent_pages'").fetchone()
            db.execute("UPDATE books SET status='running' WHERE id=?", (book_id,))
        limit = max(1, min(5, int(setting[0]) if setting else 2))
        futures = {}
        with ThreadPoolExecutor(max_workers=limit) as pool:
            while True:
                with _lock:
                    if not job['pause'].is_set():
                        with connect() as db:
                            query = "SELECT page_number FROM book_pages WHERE book_id=? AND status='pending'"
                            args = [book_id]
                            if page_number is not None: query += ' AND page_number=?'; args.append(page_number)
                            pages = [r[0] for r in db.execute(query + ' ORDER BY page_number', args) if r[0] not in futures.values() and (retry_pages is None or r[0] in retry_pages)]
                        for number in pages[:limit-len(futures)]:
                            futures[pool.submit(extract_page, book_id, number, job['pause'])] = number
                if not futures: break
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in done:
                    futures.pop(future)
                    try: future.result()
                    except SchedulingPaused: pass
                    except KeysUnavailable:
                        reason = 'keys_unavailable'; job['pause'].set()
                    except Exception:
                        reason = 'application_error'; job['pause'].set()
    except Exception:
        reason = 'application_error'
    finally:
        try:
            with connect() as db:
                counts = dict(db.execute('SELECT status,COUNT(*) FROM book_pages WHERE book_id=? GROUP BY status', (book_id,)).fetchall())
                state = reason or ('paused' if job['pause'].is_set() else 'completed' if not any(counts.get(s,0) for s in ('pending','processing','failed')) else 'stopped')
                db.execute('UPDATE books SET status=? WHERE id=?', (state, book_id))
        finally:
            with _lock: _jobs.pop(book_id, None)

def start(book_id, retry_failed=False, page_number=None, rerender_failed=False):
    with _lock:
        if book_id in _jobs: return False
        with connect() as db:
            if not db.execute('SELECT 1 FROM books WHERE id=?', (book_id,)).fetchone(): return False
        job = {'pause': Event()}; _jobs[book_id] = job
        job['thread'] = Thread(target=_run, args=(book_id,job,retry_failed,page_number,rerender_failed), daemon=True)
        job['thread'].start()
        return True

def rerender_failed_page(book_id, page_number):
    """Retry one failed physical page through a brand-new full-page PDF render."""
    return start(book_id, page_number=page_number, rerender_failed=True)

def pause(book_id):
    with _lock:
        if book_id not in _jobs: return False
        _jobs[book_id]['pause'].set()
        return True

def active(book_id):
    with _lock: return book_id in _jobs

def state(book_id):
    with _lock:
        job = _jobs.get(book_id)
        return ('pausing' if job['pause'].is_set() else 'running') if job else None


def shutdown():
    with _lock:
        jobs = list(_jobs.values())
        for job in jobs: job['pause'].set()
    for job in jobs: job['thread'].join()

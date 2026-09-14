from datetime import datetime
import json
import random
import threading
import pymupdf
from .database import connect
from .ocr_prompt import OCR_SYSTEM_INSTRUCTION
from .search_service import normalize_arabic
from .gemini_key_manager import acquire_key, record_request, KeysUnavailable, SchedulingPaused

MAX_ATTEMPTS = 4
_render_lock = threading.Lock()  # PyMuPDF does not support concurrent document operations.

class PageFailure(Exception):
    pass

def classify_gemini_error(exc):
    text = (type(exc).__name__ + ' ' + str(exc) + ' ' + str(getattr(exc, 'code', ''))).upper()
    if any(x in text for x in ('REQUESTSPERDAY', 'REQUESTS_PER_DAY', 'PER DAY', 'DAILY QUOTA', 'TOKENS_PER_DAY', 'TOKENSPERDAY')):
        return 'quota_exhausted'
    if any(x in text for x in ('401', '403', 'INVALID API KEY', 'API_KEY_INVALID', 'UNAUTHENTICATED', 'PERMISSION_DENIED')):
        return 'invalid_key'
    if '429' in text or 'RESOURCE_EXHAUSTED' in text or 'RATE LIMIT' in text: return 'rate_limited'
    if isinstance(exc, (TimeoutError, ConnectionError)) or any(x in text for x in ('TIMEOUT', 'TIMED OUT', 'CONNECTION', 'NETWORK', 'TEMPORARY', 'CONNECTERROR', 'READERROR', 'WRITEERROR', 'PROTOCOLERROR')): return 'network_error'
    if any(x in text for x in ('500', '502', '503', '504')): return 'service_error'
    return 'permanent_request'

def retry_delay(exc, attempt):
    import re
    delay = min(60, 4 * 2 ** attempt) + random.uniform(0, 2)
    headers = getattr(getattr(exc, 'response', None), 'headers', {}) or {}
    hint = headers.get('retry-after', '')
    try: delay = max(delay, float(hint))
    except (ValueError, TypeError): pass
    match = re.search(r'(?:retryDelay[\"\s:]+|retry in\s+)([0-9.]+)s', str(exc), re.I)
    if match: delay = max(delay, float(match.group(1)))
    return min(delay, 3600)

def is_quota_error(exc):
    return classify_gemini_error(exc) == 'quota_exhausted'

def _diagnostic(exc, stage, key_id):
    """Return only low-risk, bounded provider failure metadata."""
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', {}) or {}
    status = getattr(exc, 'code', None) or getattr(exc, 'status_code', None) or getattr(response, 'status_code', None) or getattr(response, 'status', None)
    retry_after = headers.get('retry-after') or headers.get('Retry-After')
    if retry_after is not None:
        retry_after = str(retry_after)[:32]
    return {'category': classify_gemini_error(exc), 'status': str(status)[:32] if status is not None else None,
            'exception': type(exc).__name__[:80], 'retry_after': retry_after,
            'stage': stage, 'key': str(key_id)[:80]}

def _diagnostic_summary(records):
    fields = ('category', 'status', 'exception', 'retry_after', 'stage', 'key')
    parts = []
    for record in records:
        parts.append(','.join(f'{field}={record[field]}' for field in fields if record.get(field) is not None))
    return ' | '.join(parts)[:1200]

def generate(key, image, model, thinking, mime_type='image/png'):
    from google import genai
    from google.genai import types
    with genai.Client(api_key=key, http_options=types.HttpOptions(timeout=120000, retry_options=types.HttpRetryOptions(attempts=1))) as client:
        response = client.models.generate_content(model=model, contents=[types.Part.from_bytes(data=image, mime_type=mime_type)], config=types.GenerateContentConfig(system_instruction=OCR_SYSTEM_INSTRUCTION, thinking_config=types.ThinkingConfig(thinking_level=thinking)))
        if response.text is None: raise RuntimeError('503 Empty OCR response')
        return response.text

def _state(book_id, page_number, status, kind=None, diagnostics=None):
    message = 'تعذر استخراج هذه الصفحة بعد عدة محاولات. تم تخطيها ومتابعة بقية الكتاب.' if kind == 'page_service_failure' else kind
    if kind == 'page_service_failure' and diagnostics:
        message += ' Diagnostic: ' + _diagnostic_summary(diagnostics)
    with connect() as db:
        db.execute("UPDATE book_pages SET status=?,error_kind=?,error_message=?,updated_at=? WHERE book_id=? AND page_number=? AND status='processing'", (status, kind, message, datetime.now().isoformat(), book_id, page_number))

def extract_page(book_id, page_number, stop=None):
    stop = stop or threading.Event()
    with connect() as db:
        book = db.execute('SELECT * FROM books WHERE id=?', (book_id,)).fetchone()
        settings = {r['key']: r['value'] for r in db.execute('SELECT * FROM settings')}
        claimed = db.execute("UPDATE book_pages SET status='processing',error_message=NULL,error_kind=NULL,updated_at=? WHERE book_id=? AND page_number=? AND status='pending'", (datetime.now().isoformat(), book_id, page_number)).rowcount
    if not claimed: return False
    model = settings.get('gemini_model') or 'gemini-3.1-flash-lite'
    thinking = settings.get('thinking_level') or 'minimal'
    try:
        if not book: raise PageFailure('Book no longer exists')
        def render(scale, image_format='png', quality=80):
            with _render_lock, pymupdf.open(book['file_path']) as pdf:
                pix = pdf[page_number-1].get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                return pix.tobytes(image_format, jpg_quality=quality) if image_format == 'jpeg' else pix.tobytes('png')
        try:
            image = render(2.5)
        except Exception:
            raise PageFailure('PDF page could not be rendered') from None
        attempts = 0
        transient_keys = set()
        fallback_used = False
        diagnostics = []
        while attempts < MAX_ATTEMPTS:
            key = acquire_key(settings.get('ocr_key_mode', 'single'), json.loads(settings.get('ocr_pool_ids', '[]')), stop)
            request_day = record_request(key['id'])
            try:
                text = generate(key['api_key'], image, model, thinking)
            except Exception as exc:
                kind = classify_gemini_error(exc)
                diagnostics.append(_diagnostic(exc, 'normal_png', key['id']))
                delay = retry_delay(exc, attempts)
                record_request(key['id'], success=False, status=kind, cooldown=delay if kind == 'rate_limited' else 0, request_day=request_day)
                if kind in ('quota_exhausted', 'invalid_key'): continue
                if kind in ('network_error', 'service_error'):
                    transient_keys.add(key['id'])
                    if len(transient_keys) >= 2:
                        if not fallback_used:
                            fallback_used = True
                            try:
                                image = render(1.5)
                                fallback_text = generate(key['api_key'], image, model, thinking)
                            except Exception as exc:
                                diagnostics.append(_diagnostic(exc, 'reduced_png', key['id']))
                                try:
                                    image = render(1.3, 'jpeg', quality=76)
                                    fallback_text = generate(key['api_key'], image, model, thinking, mime_type='image/jpeg')
                                except Exception as exc:
                                    diagnostics.append(_diagnostic(exc, 'jpeg_fallback', key['id']))
                                    fallback_text = None
                            if fallback_text is not None:
                                text = fallback_text
                                with connect() as db:
                                    row = db.execute("SELECT id FROM book_pages WHERE book_id=? AND page_number=? AND status='processing'", (book_id, page_number)).fetchone()
                                    if row:
                                        db.execute("UPDATE book_pages SET status='completed',extracted_text=?,line_count=?,model=?,thinking_level=?,error_message=NULL,error_kind=NULL,updated_at=? WHERE id=?", (text, len(text.splitlines()), model, thinking, datetime.now().isoformat(), row['id']))
                                        db.execute('DELETE FROM page_search WHERE page_id=?', (row['id'],)); db.execute('INSERT INTO page_search VALUES(?,?,?)', (row['id'], text, normalize_arabic(text)))
                                        record_request(key['id'], success=True, status='available', request_day=request_day); return True
                        _state(book_id, page_number, 'failed', 'page_service_failure', diagnostics); return False
                attempts += 1
                if kind == 'permanent_request' or attempts >= MAX_ATTEMPTS:
                    _state(book_id, page_number, 'failed', kind)
                    return False
                if kind != 'rate_limited' and stop.wait(delay): raise SchedulingPaused()
                continue
            record_request(key['id'], success=True, status='available', request_day=request_day)
            # Text and its derived index commit atomically; never reprocess completed text.
            with connect() as db:
                row = db.execute("SELECT id FROM book_pages WHERE book_id=? AND page_number=? AND status='processing'", (book_id, page_number)).fetchone()
                if not row: return False
                db.execute("UPDATE book_pages SET status='completed',extracted_text=?,line_count=?,model=?,thinking_level=?,error_message=NULL,error_kind=NULL,updated_at=? WHERE id=?", (text, len(text.splitlines()), model, thinking, datetime.now().isoformat(), row['id']))
                db.execute('DELETE FROM page_search WHERE page_id=?', (row['id'],))
                db.execute('INSERT INTO page_search VALUES(?,?,?)', (row['id'], text, normalize_arabic(text)))
            return True
    except (KeysUnavailable, SchedulingPaused):
        _state(book_id, page_number, 'pending')
        raise
    except PageFailure:
        _state(book_id, page_number, 'failed', 'permanent_request')
        return False
    except Exception:
        _state(book_id, page_number, 'pending', 'application_error')
        raise RuntimeError('OCR stopped safely after an application error; check local storage and settings.') from None

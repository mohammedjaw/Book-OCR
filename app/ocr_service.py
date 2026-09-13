from datetime import datetime
import time
import pymupdf
from .database import connect
from .ocr_prompt import OCR_SYSTEM_INSTRUCTION
from .secrets import load_secrets
from .search_service import index_page

def extract_page(book_id, page_number):
    from google import genai
    from google.genai import types
    with connect() as db:
        book = db.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        settings = {r['key']: r['value'] for r in db.execute("SELECT * FROM settings")}
    key = load_secrets().get('gemini_api_key')
    if not book or not key: raise ValueError("لم يتم إعداد مفتاح Gemini")
    model=settings.get('gemini_model') or 'gemini-3.1-flash-lite'; thinking=settings.get('thinking_level') or 'minimal'; now=datetime.now().isoformat(timespec='seconds')
    with connect() as db: db.execute("UPDATE book_pages SET status='processing',error_message=NULL,updated_at=? WHERE book_id=? AND page_number=?",(now,book_id,page_number))
    try:
        with pymupdf.open(book['file_path']) as pdf:
            if page_number < 1 or page_number > len(pdf): raise ValueError("رقم الصفحة غير صالح")
            image=pdf[page_number-1].get_pixmap(matrix=pymupdf.Matrix(2.5,2.5),alpha=False).tobytes('png')
        client = genai.Client(api_key=key)
        config=types.GenerateContentConfig(system_instruction=OCR_SYSTEM_INSTRUCTION,thinking_config=types.ThinkingConfig(thinking_level=thinking))
        for attempt in range(3):
            try:
                response=client.models.generate_content(model=model,contents=[types.Part.from_bytes(data=image,mime_type='image/png')],config=config); break
            except Exception as exc:
                transient=any(x in str(exc).upper() for x in ('429','RESOURCE_EXHAUSTED','RATE LIMIT','TIMEOUT','CONNECTION'))
                if attempt == 2 or not transient: raise
                time.sleep(2 ** attempt)
        text=response.text or ''; now=datetime.now().isoformat(timespec='seconds')
        with connect() as db: db.execute("UPDATE book_pages SET status='completed',extracted_text=?,line_count=?,model=?,thinking_level=?,error_message=NULL,updated_at=? WHERE book_id=? AND page_number=?",(text,len(text.splitlines()),model,thinking,now,book_id,page_number))
        with connect() as db: page_id=db.execute('SELECT id FROM book_pages WHERE book_id=? AND page_number=?',(book_id,page_number)).fetchone()['id']
        index_page(page_id,text)
    except Exception as exc:
        detail = str(exc).replace(key, '[مخفي]')[:300]
        message = ('رقم الصفحة غير صالح' if isinstance(exc, ValueError) else type(exc).__name__ + ': ' + detail)
        with connect() as db: db.execute("UPDATE book_pages SET status='failed',error_message=?,updated_at=? WHERE book_id=? AND page_number=?",(message,datetime.now().isoformat(timespec='seconds'),book_id,page_number))
        raise ValueError(message)

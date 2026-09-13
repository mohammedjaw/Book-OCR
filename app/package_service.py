import hashlib,json,tempfile,zipfile
from pathlib import Path
from datetime import datetime
from .database import connect
from .search_service import rebuild_search_index
from .export_service import filename

def export_package(uid):
    with connect() as db:
        b=db.execute('SELECT * FROM books WHERE book_uuid=?',(uid,)).fetchone(); pages=db.execute('SELECT * FROM book_pages WHERE book_id=? ORDER BY page_number',(b['id'],)).fetchall()
    pdf=Path(b['file_path']); manifest={'format':'Book-OCR-Package','format_version':1,'book_uuid':b['book_uuid'],'title':b['title'],'original_filename':b['original_filename'],'page_count':b['page_count'],'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'created_at':b['created_at'],'exported_at':datetime.now().isoformat(timespec='seconds'),'app_version':'0.2.2'}
    data=[{'page_number':p['page_number'],'status':p['status'],'extracted_text':p['extracted_text'],'line_count':p['line_count'],'model':p['model'],'thinking_level':p['thinking_level'],'error_message':p['error_message'],'created_at':p['created_at'],'updated_at':p['updated_at']} for p in pages]
    f=tempfile.NamedTemporaryFile(suffix='.bookocr.zip',delete=False); f.close()
    with zipfile.ZipFile(f.name,'w',zipfile.ZIP_DEFLATED) as z: z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)); z.writestr('pages.json',json.dumps(data,ensure_ascii=False,indent=2)); z.write(pdf,'original.pdf')
    return f.name,filename(b['title'],'.bookocr.zip')

def import_package(upload):
    with zipfile.ZipFile(upload,'r') as z:
        names=set(z.namelist())
        if not {'manifest.json','pages.json','original.pdf'} <= names or any(Path(n).is_absolute() or '..' in Path(n).parts for n in names): raise ValueError('حزمة غير صالحة')
        m=json.loads(z.read('manifest.json')); pages=json.loads(z.read('pages.json')); pdf=z.read('original.pdf')
    if m.get('format')!='Book-OCR-Package' or m.get('format_version')!=1 or hashlib.sha256(pdf).hexdigest()!=m.get('sha256'): raise ValueError('فشل التحقق من سلامة الحزمة')
    if len(pages)!=m.get('page_count') or [p.get('page_number') for p in pages]!=list(range(1,len(pages)+1)): raise ValueError('صفحات الحزمة غير صحيحة')
    from .book_manager import BOOKS
    uid=m['book_uuid'];
    with connect() as db:
        if db.execute('SELECT 1 FROM books WHERE file_hash=?',(m['sha256'],)).fetchone(): raise ValueError('هذا الكتاب موجود مسبقًا في المكتبة بنفس ملف PDF.')
        if db.execute('SELECT 1 FROM books WHERE book_uuid=?',(uid,)).fetchone(): raise ValueError('هذه الحزمة مستوردة مسبقًا أو يوجد كتاب بنفس المعرّف.')
        target=BOOKS/(uid+'_imported.pdf'); target.write_bytes(pdf)
        now=datetime.now().isoformat(timespec='seconds'); cur=db.execute('INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,m['title'],m['original_filename'],target.name,str(target),m['sha256'],m['page_count'],'جاهز',now,now))
        for p in pages: db.execute('INSERT INTO book_pages(book_id,page_number,status,extracted_text,line_count,model,thinking_level,error_message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(cur.lastrowid,p['page_number'],p['status'],p.get('extracted_text'),p.get('line_count'),p.get('model'),p.get('thinking_level'),p.get('error_message'),p.get('created_at',now),p.get('updated_at',now)))
    rebuild_search_index(); return uid

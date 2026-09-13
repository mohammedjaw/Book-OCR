import re
from markupsafe import Markup, escape
from .database import connect
def normalize_arabic(text):
    return re.sub('[\\u064B-\\u065F\\u0670]','',text or '').replace('ـ','').translate(str.maketrans({'أ':'ا','إ':'ا','آ':'ا','ٱ':'ا'}))
def rebuild_search_index():
    with connect() as db:
        db.execute('DELETE FROM page_search')
        for p in db.execute("SELECT id,extracted_text FROM book_pages WHERE status='completed' AND extracted_text IS NOT NULL"):
            db.execute('INSERT INTO page_search(page_id,exact_text,normalized_text) VALUES(?,?,?)',(p['id'],p['extracted_text'],normalize_arabic(p['extracted_text'])))
def index_page(page_id,text):
    with connect() as db:
        db.execute('DELETE FROM page_search WHERE page_id=?',(page_id,))
        if text is not None: db.execute('INSERT INTO page_search VALUES(?,?,?)',(page_id,text,normalize_arabic(text)))
def search_pages(query,mode='exact',book_id=None,limit=25,offset=0):
    column='normalized_text' if mode=='flexible' else 'exact_text'; term=query.strip().replace('"',' ')
    with connect() as db:
        sql=f"SELECT p.*,b.book_uuid,b.title FROM page_search AS s JOIN book_pages p ON p.id=s.page_id JOIN books b ON b.id=p.book_id WHERE page_search MATCH ?"
        args=[f'{column}:({term})']
        if book_id: sql+=' AND p.book_id=?'; args.append(book_id)
        sql+=' ORDER BY rank LIMIT ? OFFSET ?'; args += [limit,offset]
        return db.execute(sql,args).fetchall()
def count_pages(query,mode='exact',book_id=None):
    column='normalized_text' if mode=='flexible' else 'exact_text'; term=query.strip().replace('"',' '); sql='SELECT COUNT(*) FROM page_search WHERE page_search MATCH ?'; args=[f'{column}:({term})']
    if book_id: sql+=' AND page_id IN (SELECT id FROM book_pages WHERE book_id=?)'; args.append(book_id)
    with connect() as db: return db.execute(sql,args).fetchone()[0]
def highlight_text(text, query, mode='exact'):
    text=text or ''; query=query or ''
    if not query.strip(): return escape(text)
    if mode=='exact': spans=[m.span() for m in re.finditer(re.escape(query),text)]
    else:
        norm=[]; positions=[]
        for i,ch in enumerate(text):
            n=normalize_arabic(ch)
            for out in n: norm.append(out); positions.append(i)
        nq=normalize_arabic(query); spans=[]
        for m in re.finditer(re.escape(nq),''.join(norm)):
            spans.append((positions[m.start()],positions[m.end()-1]+1))
    out=[]; end=0
    for a,b in spans:
        out.extend([escape(text[end:a]),Markup('<mark class="search-highlight">'),escape(text[a:b]),Markup('</mark>')]); end=b
    out.append(escape(text[end:])); return Markup('').join(out)
def count_matches(text,query,mode='exact'):
    rendered=highlight_text(text,query,mode); return str(rendered).count('search-highlight')

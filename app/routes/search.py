from fastapi import APIRouter,Request
from fastapi.templating import Jinja2Templates
from ..database import connect
from ..search_service import search_pages, highlight_text, count_matches, count_pages, parse_scope
from ..ui import templates; router=APIRouter()
@router.get('/search')
def search(request:Request,q:str='',mode:str='exact',book_id:str|None=None,page:int=1):
    selected_book_id, selected_collection_id = parse_scope(book_id)
    page=max(1,page)
    results=[dict(r) for r in search_pages(q,mode,selected_book_id,25,(page-1)*25,collection_id=selected_collection_id)] if q.strip() else []
    for r in results: r['highlight']=highlight_text(r['extracted_text'],q,mode); r['matches']=count_matches(r['extracted_text'],q,mode)
    with connect() as db:
        books=db.execute('SELECT id,title FROM books WHERE collection_id IS NULL ORDER BY title').fetchall()
        collections=db.execute('SELECT id,title FROM collections ORDER BY title,id').fetchall()
        selected_volume=db.execute('SELECT id,title FROM books WHERE id=? AND collection_id IS NOT NULL',(selected_book_id,)).fetchone() if selected_book_id else None
    total=count_pages(q,mode,selected_book_id,collection_id=selected_collection_id) if q.strip() else 0
    return templates.TemplateResponse(request=request,name='search.html',context={'query':q,'mode':mode,'book_id':book_id or 'all','page':page,'total':total,'pages_total':max(1,(total+24)//25),'results':results,'books':books,'collections':collections,'selected_volume':selected_volume})

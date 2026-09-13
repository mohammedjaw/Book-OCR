from fastapi import APIRouter,Request
from fastapi.templating import Jinja2Templates
from ..database import connect
from ..search_service import search_pages, highlight_text, count_matches, count_pages
templates=Jinja2Templates(directory='templates'); router=APIRouter()
@router.get('/search')
def search(request:Request,q:str='',mode:str='exact',book_id:str|None=None,page:int=1):
    selected_book_id = int(book_id) if book_id and book_id != 'all' else None
    results=[dict(r) for r in search_pages(q,mode,selected_book_id,25,(page-1)*25)] if q.strip() else []
    for r in results: r['highlight']=highlight_text(r['extracted_text'],q,mode); r['matches']=count_matches(r['extracted_text'],q,mode)
    with connect() as db: books=db.execute('SELECT id,title FROM books ORDER BY title').fetchall()
    total=count_pages(q,mode,selected_book_id) if q.strip() else 0
    return templates.TemplateResponse(request=request,name='search.html',context={'query':q,'mode':mode,'book_id':book_id or 'all','page':page,'total':total,'pages_total':max(1,(total+24)//25),'results':results,'books':books})

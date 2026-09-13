from fastapi import APIRouter,Request,UploadFile,File
from fastapi.responses import RedirectResponse
from ..package_service import import_package
from fastapi.templating import Jinja2Templates
templates=Jinja2Templates(directory="templates"); router=APIRouter()
@router.get("/transfer")
def transfer(request:Request): return templates.TemplateResponse(request=request, name="transfer.html", context={})
@router.post('/transfer/import')
def import_book(request:Request,file:UploadFile=File(...)):
    try: uid=import_package(file.file); return RedirectResponse(f'/books/{uid}',303)
    except ValueError as e: return templates.TemplateResponse(request=request,name='transfer.html',context={'error':str(e)},status_code=400)

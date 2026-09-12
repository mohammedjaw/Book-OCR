from fastapi import APIRouter,Request
from fastapi.templating import Jinja2Templates
templates=Jinja2Templates(directory="templates"); router=APIRouter()
@router.get("/transfer")
def transfer(request:Request): return templates.TemplateResponse(request=request, name="transfer.html", context={})

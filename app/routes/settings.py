from fastapi import APIRouter,Request,Form
from fastapi.templating import Jinja2Templates
from ..database import connect
from ..secrets import load_secrets, save_secrets
templates=Jinja2Templates(directory="templates"); router=APIRouter()
@router.get("/settings")
def settings(request:Request):
    with connect() as db: s={r["key"]:r["value"] for r in db.execute("SELECT * FROM settings")}
    s["gemini_api_key"] = "••••••••" if load_secrets().get("gemini_api_key") else ""
    return templates.TemplateResponse(request=request, name="settings.html", context={"settings":s,"message":None})
@router.post("/settings")
def save(request:Request,api_key:str=Form(""),model:str=Form(""),thinking:str=Form("minimal")):
    with connect() as db:
        if not api_key:
            api_key = load_secrets().get("gemini_api_key", "")
        save_secrets({"gemini_api_key": api_key})
        for k,v in (("gemini_model",model),("thinking_level",thinking)): db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",(k,v))
    return templates.TemplateResponse(request=request, name="settings.html", context={"settings":{"gemini_api_key":"••••••••" if api_key else "","gemini_model":model,"thinking_level":thinking},"message":"تم حفظ الإعدادات"})

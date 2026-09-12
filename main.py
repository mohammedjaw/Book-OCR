from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
from app.database import init_db
from app.routes import home, books, settings, search, transfer

BASE = Path(__file__).parent
for folder in ("data", "books", "exports", "config", "static/css", "static/js", "static/pdfjs"):
    (BASE / folder).mkdir(parents=True, exist_ok=True)
init_db()

app = FastAPI(title="مكتبة Book-OCR", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
app.include_router(home.router)
app.include_router(books.router)
app.include_router(settings.router)
app.include_router(search.router)
app.include_router(transfer.router)

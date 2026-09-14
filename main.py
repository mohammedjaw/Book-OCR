from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from app import database
from app.routes import home, books, settings, search, transfer, collections
from app.search_service import rebuild_search_index
from app.ocr_worker import recover_stale, shutdown
from app.lifecycle import library_lock

BASE = Path(__file__).parent

@asynccontextmanager
async def lifespan(app):
    with library_lock(database.DB.with_suffix('.lock')):
        for folder in ('data','books','exports','config'):
            (BASE/folder).mkdir(parents=True,exist_ok=True)
        database.init_db()
        from app.book_manager import recover_interrupted_deletions
        recover_interrupted_deletions()
        recover_stale()
        rebuild_search_index()
        try: yield
        finally: await run_in_threadpool(shutdown)

app = FastAPI(title='Book-OCR',version='0.1.0',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')
for module in (home,books,settings,search,transfer,collections): app.include_router(module.router)

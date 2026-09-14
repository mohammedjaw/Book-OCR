"""Disposable collection UI fixture. Never opens the real library or Gemini."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_collections import CollectionTests
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routes import books, collections, search
from app import database
import uvicorn

if __name__=='__main__':
    fixture=CollectionTests();fixture.setUp()
    cid,uid=fixture.create()
    for i in range(3): fixture.assign(uid,i,i+1)
    app=FastAPI()
    for module in (books,collections,search): app.include_router(module.router)
    app.mount('/static',StaticFiles(directory='static'),name='static')
    @app.middleware('http')
    async def fixture_preferences(request,call_next):
        with database.connect() as db:
            for param,key,allowed in [('lang','ui_language',('en','ar','fa')),('theme','theme',('فاتح','داكن','تلقائي'))]:
                value=request.query_params.get(param)
                if value in allowed: db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,value))
        return await call_next(request)
    print(f'DISPOSABLE_COLLECTION=http://127.0.0.1:8766/collections/{uid}',flush=True)
    try: uvicorn.run(app,host='127.0.0.1',port=8766,log_level='warning')
    finally: fixture.tearDown()

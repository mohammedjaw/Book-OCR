"""Disposable browser verification server. No real Gemini calls or library access."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_stabilization import StabilizationTests
from unittest.mock import patch
from fastapi.staticfiles import StaticFiles
import time
import uvicorn
from app import ocr_service,gemini_key_manager

fixture=StabilizationTests()
fixture.setUp()
app=fixture.client().app
app.mount('/static',StaticFiles(directory='static'),name='static')
def synthetic(*args):
    time.sleep(4)
    return 'أَصل الكتاب\nمتن فارسی\nFull original OCR text — unchanged.'
if __name__=='__main__':
    print('MOCK_BOOK_URL=http://127.0.0.1:8765/books/'+fixture.uid,flush=True)
    try:
        with patch.object(ocr_service,'generate',side_effect=synthetic),patch.object(gemini_key_manager,'REQUEST_INTERVAL',1):
            uvicorn.run(app,host='127.0.0.1',port=8765,log_level='warning')
    finally: fixture.tearDown()

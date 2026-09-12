# Book-OCR 0.1

Windows setup:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

Open http://127.0.0.1:8000. OCR, FTS5 search, and package transfer are reserved for later versions.

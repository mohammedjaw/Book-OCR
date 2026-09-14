# Book-OCR

Local PDF OCR, search, reading, export, and portable book transfer with FastAPI, SQLite, PyMuPDF, and Gemini.

On Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8000
```

Run from the project directory. Use one server process per library; a library lock prevents two servers from claiming the same pages. For unattended OCR, leave the server running and avoid development `--reload`. Browser navigation and closing a tab do not stop OCR.

In Settings, add keys and choose Single Key or an explicit Multi-Key Pool. New installations default to two concurrent pages (configurable 1–5). Existing saved concurrency is preserved. Request starts are spaced at least two seconds apart across jobs; temporary key rate limits extend that key's wait. Keys belonging to the same Google project may share quota.

Start/Resume processes pending pages. Pause drains active calls and stops further calls. Retry eligible failed pages processes only that failed subset; it does not restart completed or previously pending pages. Permanent request failures remain visible for diagnosis. Confirmed daily exhaustion disables the affected key until the next America/Los_Angeles day; when all selected keys are unusable, remaining pages stay pending. Resume explicitly after fixing settings or waiting for the reset.

The book page refreshes status every three seconds during work and every fifteen seconds when idle. Full-page reading links to the same physical PDF page; full-book text loads twenty physical pages per segment. Word, JSON, and portable ZIP exports unlock when every page is complete. The original PDF is always downloadable.

Portable packages contain only a manifest, original PDF bytes, and OCR page data. Import validates the archive, version, UUID, page sequence/count, and PDF hash, and indexes the imported text in the same database transaction. Current import limits are 2 GiB for the PDF and 256 MiB for page JSON. Delete Book requires a separate confirmation and refuses deletion while a worker is draining.

Saved UI preferences live in SQLite; secrets and LOCAL usage counters live in `config/secrets.json`. Counters describe calls made by this app, not Google's official quota. Startup performs an additive schema migration, recovers interrupted processing to pending, and rebuilds derived search indexes without changing stored OCR text.

Run regression tests (temporary databases and synthetic Gemini responses only):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_polling.cjs
```

`test_gemini_ocr.py` is a manual live-generation script. It runs only when invoked directly, never during test discovery. `tests/browser_fixture.py` starts a disposable mocked browser test server on port 8765.

See `STABILIZATION_REPORT.md` for findings, changes, verification, and remaining limitations.

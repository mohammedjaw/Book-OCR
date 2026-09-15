# Book-OCR — Local-First OCR Library for Scanned Books

Turn large scanned PDF books into searchable, structured digital libraries with high-fidelity OCR, full-text search, collections, portable backups, and a self-contained Windows app.

Book-OCR is built with a strong focus on historical Arabic books and faithful page-by-page transcription. It preserves the original PDF, keeps OCR text aligned with physical pages, and stores the library on your own computer.

## Why Book-OCR?

Large scanned books—especially historical Arabic works—are difficult to search, navigate, organize, and preserve as structured text. Generic OCR workflows often lose the relationship between extracted text and the original physical page or silently “correct” historical spelling.

Book-OCR takes a local-first, library-oriented approach. Books, page text, search indexes, collections, settings, and exports are managed locally. When OCR is requested, Book-OCR sends a rendered image of that page to the configured Gemini API; the local database and other books are not part of that OCR request.

## Key Features

- A page-by-page OCR workflow designed for high-fidelity transcription
- A transcription prompt designed to preserve wording, historical spelling, line structure, symbols, and unclear text instead of editorially correcting it
- Original PDF preservation and exact OCR-to-PDF page mapping
- Local SQLite library with FTS5 full-text search
- Exact search plus flexible Arabic search that normalizes diacritics, tatweel, and common alif variants
- Multi-volume collections, volume ordering, collection-aware navigation, and collection-scoped search
- Page reader, full-book OCR view, and direct navigation to the matching PDF page
- JSON, Microsoft Word, original-PDF, and portable package exports where available
- Portable individual-book packages containing the original PDF and completed OCR text
- Portable complete-collection packages with ordered volumes and integrity validation
- Password-encrypted `.bookocr-keys` backup and restore for saved Gemini API keys
- Single-key or explicit multi-key Gemini pools with key fallback and per-key quota/error isolation
- Arabic, English, and Persian interface options with RTL/LTR support
- Light, dark, and system theme modes
- Self-contained 64-bit Windows application with no Python installation required
- Loopback-only local web server and user data stored outside the application folder

## Screenshots

Publication-safe screenshots are not included yet. Screenshots added in the future must use synthetic or redistributable sample material and must not expose API keys, private books, personal paths, or user library data.

## Windows Download

For ordinary Windows use, open [GitHub Releases](https://github.com/mohammedjaw/Book-OCR/releases) and download:

`Book-OCR-0.2.3-Windows-x64.zip`

No Python installation is required for this build. Extract the complete ZIP before running the application.

> **Do not copy `Book-OCR.exe` by itself.** Keep the adjacent `_internal` folder and `QUICK_START.txt` with the executable.

The packaged application is currently validated for 64-bit Windows. No packaged macOS or Linux release is currently provided.

## Quick Start

1. Download `Book-OCR-0.2.3-Windows-x64.zip` from GitHub Releases.
2. Extract the entire `Book-OCR-0.2.3-Windows-x64` folder.
3. Run `Book-OCR.exe`.
4. Your default browser opens the local Book-OCR interface.
5. Add a Gemini API key in **Settings** if you want to perform OCR.
6. Existing library, search, PDF viewing, import, and export features continue to operate locally.

The launcher opens the friendly browser address [http://book-ocr.localhost:8765](http://book-ocr.localhost:8765). If an older browser does not support the reserved `.localhost` name, use [http://localhost:8765](http://localhost:8765) instead. The application server itself binds only to `127.0.0.1`.

## Data Location

The packaged Windows application stores persistent data under:

```text
%LOCALAPPDATA%\Book-OCR\
```

This location contains the SQLite library, original PDFs, exports, and local configuration. Replacing or updating the extracted application folder does not remove this separate library data. Close Book-OCR before copying the data folder for a filesystem-level backup.

Source checkouts keep their development data folders beside the source tree instead.

## Internet Requirements

Gemini OCR and Gemini connection testing require network access and a valid API key. OCR requests necessarily send rendered page content to the configured Gemini API.

Browsing an existing local library, searching previously extracted text, viewing stored PDFs, managing collections, and generating local exports do not require Gemini. Book-OCR does not claim that its Gemini-powered OCR process is offline.

## Privacy & Security

- The application server listens on `127.0.0.1`, with no LAN exposure by default.
- Books, OCR text, the SQLite search index, and exports remain in the local data directory except when a page is sent to Gemini for OCR.
- Gemini API keys are stored locally in the sensitive `config\secrets.json` file beneath the data directory; Book-OCR does not claim that file is encrypted at rest.
- API-key backup files use password-derived authenticated encryption (AES-256-GCM with scrypt).
- No user library, API key, database, or private PDF belongs in the source repository or a GitHub Release.

See [SECURITY.md](SECURITY.md) for responsible reporting guidance.

## API Key Backup

Settings can export saved Gemini API keys and active-key metadata to a password-encrypted `.bookocr-keys` file and restore them later in merge or replace mode. The password is not stored by Book-OCR. Keep the backup file and its password separately; the backup contains credentials even though its contents are encrypted.

## Collections

Books can be grouped into named multi-volume collections with explicit volume numbers. Search can be limited to the full collection, and reader navigation retains collection context.

A collection package can be exported only when every volume has OCR text for every page. This completeness rule prevents a package from appearing portable while silently omitting unfinished content.

## Portable Packages

An individual book package contains a format manifest, the original PDF, and completed page-level OCR data. A collection package contains collection metadata and the corresponding portable content for each ordered volume. Imports validate archive structure, identifiers, page counts, PDF hashes, and supported format versions before committing data.

These packages are intended for transfer between Book-OCR libraries. Treat them as sensitive whenever the underlying books or OCR text are private or copyrighted.

## Development Setup

Python 3.14.5 is the currently validated development and Windows build version.

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

Alternatively, after installing dependencies, run the desktop-style development launcher:

```powershell
python launcher.py
```

The launcher uses port 8765 by default and does not enable Uvicorn reload mode. A development-only port override can be placed in the ignored `config\launcher.json` file as `{ "port": 8767 }`.

Do not run `test_gemini_ocr.py` during routine development or release validation; it is a manual live-API diagnostic.

## Windows Build

Install the build-only dependency once, then use the reproducible build command:

```powershell
python -m pip install -r requirements-build.txt
.\build_windows.ps1
```

The validated PyInstaller `onedir` output is:

```text
dist\Book-OCR\
```

It contains `Book-OCR.exe`, `_internal`, and `QUICK_START.txt`. The executable is built with `console=False`; dependencies and the Python runtime are bundled inside the distribution.

## Testing

The automated tests use temporary databases, generated PDF fixtures, and mocked Gemini responses. They do not require or call a real Gemini API.

```powershell
python -m unittest discover -s tests -v
node tests/test_polling.cjs
git diff --check
```

`test_gemini_ocr.py` is excluded from discovery and must be invoked explicitly; do not run it for offline validation.

## Architecture

- **FastAPI + Uvicorn** — local application server and routes
- **Jinja2** — server-rendered interface
- **SQLite + FTS5** — library metadata, page state, preferences, and full-text search
- **PyMuPDF** — PDF inspection, rendering, and page mapping
- **Google Gen AI SDK** — Gemini OCR requests and key-pool integration
- **python-docx** — Microsoft Word export
- **PyInstaller** — self-contained Windows `onedir` distribution

Mutable packaged data is resolved separately from bundled templates and static assets, allowing the application folder to be replaced without replacing the local library.

## Project Status

Current version: **0.2.3**.

Version 0.2.3 is the current public release and the currently validated 64-bit Windows build. See [CHANGELOG.md](CHANGELOG.md) for release history.

## Roadmap

Possible future improvements include a Windows installer, a simpler in-app update path, support for additional OCR providers, and further portable-package tooling. These are directions rather than release commitments.

## Contributing

Focused fixes and improvements are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## Security

Do not disclose API keys, private books, or credentials in a public issue. Follow [SECURITY.md](SECURITY.md) when reporting a vulnerability.

## License

Book-OCR is available under the [MIT License](LICENSE).

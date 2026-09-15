# PyInstaller onedir build. The launcher starts the same bundled executable in
# --serve mode, so the installed machine never needs a system Python runtime.
from PyInstaller.utils.hooks import collect_all, collect_data_files

pymupdf_datas, pymupdf_binaries, pymupdf_hiddenimports = collect_all("pymupdf")

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("VERSION", "."),
] + pymupdf_datas + collect_data_files("tzdata")

hiddenimports = pymupdf_hiddenimports + [
    # ``main:app`` is loaded by Uvicorn from a string in --serve mode.
    "main",
    # Uvicorn chooses protocol/loop implementations dynamically.
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    # These are imported only when OCR, settings validation, or Word export run.
    "google.genai", "google.genai.types", "docx", "docx.enum.text",
]

a = Analysis(
    ["launcher.py"], pathex=[], binaries=pymupdf_binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "unittest", "tests"], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Book-OCR",
    icon="static/book-ocr.ico", console=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas, strip=False, upx=False, name="Book-OCR",
)

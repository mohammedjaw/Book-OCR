"""Paths shared by source and frozen Book-OCR runs.

Source checkouts keep their established adjacent data folders.  A frozen
Windows distribution instead stores mutable data under LocalAppData, so the
application folder can be replaced safely during an update.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent
ASSET_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT))


def persistent_root() -> Path:
    override = os.environ.get("BOOK_OCR_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Book-OCR"
    return SOURCE_ROOT


DATA_ROOT = persistent_root()
DATABASE_FILE = DATA_ROOT / "data" / "library.db"
BOOKS_ROOT = DATA_ROOT / "books"
CONFIG_ROOT = DATA_ROOT / "config"
EXPORTS_ROOT = DATA_ROOT / "exports"


def version() -> str:
    try:
        return (ASSET_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"

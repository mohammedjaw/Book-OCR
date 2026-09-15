"""Windows-friendly local launcher for Book-OCR.

This deliberately starts the existing ``main:app`` with Uvicorn instead of
creating another application.  It is suitable for a desktop shortcut today
and keeps packaging concerns at this thin entry point for a future build.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
DEFAULT_PORT = 8765
STARTUP_TIMEOUT_SECONDS = 30
CONFIG_RELATIVE_PATH = Path("config") / "launcher.json"


def application_root() -> Path:
    """Return the folder containing this launcher, independent of cwd."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def configured_port(root: Path) -> int:
    """Read an optional user-managed port override without creating a file."""
    if getattr(sys, "frozen", False):
        from app.paths import CONFIG_ROOT
        path = CONFIG_ROOT / "launcher.json"
    else:
        path = root / CONFIG_RELATIVE_PATH
    if not path.exists():
        return DEFAULT_PORT
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("port", DEFAULT_PORT)
        port = int(value)
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT


def local_url(port: int) -> str:
    return f"http://{HOST}:{port}"

def browser_url(port: int) -> str:
    """Use the browser-reserved ``.localhost`` name for a friendly address.

    Server readiness still uses the numeric loopback address and never depends
    on operating-system DNS. Users can enter ``http://localhost:<port>``
    manually if an older browser does not implement the reserved name.
    """
    return f"http://book-ocr.localhost:{port}"


def port_is_available(port: int) -> bool:
    """Check availability without claiming or terminating another process."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return probe.connect_ex((HOST, port)) != 0


def book_ocr_is_reachable(url: str, timeout: float = 1.0) -> bool:
    """Recognize our home page, rather than treating any web service as ours."""
    try:
        with urllib.request.urlopen(url + "/", timeout=timeout) as response:
            return response.status == 200 and b"Book-OCR" in response.read(32_768)
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def intended_python(root: Path) -> str:
    """Prefer the project virtual environment, with a safe development fallback."""
    if getattr(sys, "frozen", False):
        return sys.executable
    candidate = root / ".venv" / "Scripts" / "python.exe"
    return str(candidate) if candidate.exists() else sys.executable


def start_server(root: Path, port: int) -> subprocess.Popen[str]:
    """Start the existing application only on the loopback interface."""
    command = ([sys.executable, "--serve", "--port", str(port)] if getattr(sys, "frozen", False) else [
        intended_python(root), "-m", "uvicorn", "main:app",
        "--host", HOST, "--port", str(port), "--log-level", "warning",
    ])
    return subprocess.Popen(
        command, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )


def stop_server(process: subprocess.Popen[str]) -> None:
    """Stop only the server process started by this launcher."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def startup_error(process: subprocess.Popen[str]) -> str:
    """Return a small, non-sensitive diagnostic from a failed child process."""
    if process.stderr is None:
        return ""
    try:
        return process.stderr.read().strip()[-1000:]
    except OSError:
        return ""


def wait_for_ready(url: str, process: subprocess.Popen[str], timeout: float = STARTUP_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if book_ocr_is_reachable(url):
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def launch(root: Path | None = None, *, open_browser=webbrowser.open, popen=None) -> tuple[bool, str]:
    """Open an existing Book-OCR server or start one and wait for readiness."""
    root = application_root() if root is None else Path(root)
    popen = start_server if popen is None else popen
    port = configured_port(root)
    url = local_url(port); display_url = browser_url(port)

    if book_ocr_is_reachable(url):
        open_browser(display_url)
        return True, f"Book-OCR is already running at {display_url}."
    if not port_is_available(port):
        return False, f"Book-OCR could not start because port {port} is already in use."

    process = popen(root, port)
    try:
        if wait_for_ready(url, process):
            open_browser(display_url)
            return True, f"Book-OCR is ready at {display_url}."
        diagnostic = startup_error(process)
        stop_server(process)
        suffix = f" Details: {diagnostic}" if diagnostic else ""
        return False, f"Book-OCR did not become ready within {STARTUP_TIMEOUT_SECONDS} seconds.{suffix}"
    except KeyboardInterrupt:
        stop_server(process)
        return False, "Book-OCR startup was cancelled."


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--serve":
        import argparse
        import uvicorn
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--serve", action="store_true")
        parser.add_argument("--port", type=int, default=DEFAULT_PORT)
        args = parser.parse_args()
        uvicorn.run("main:app", host=HOST, port=args.port, log_level="warning",
                    log_config=None if getattr(sys, "frozen", False) else uvicorn.config.LOGGING_CONFIG)
        return 0
    if len(sys.argv) >= 2 and sys.argv[1] == "--smoke":
        from app.paths import ASSET_ROOT, version
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from docx import Document
        from google import genai
        from google.genai import types
        from jinja2 import Environment
        from markupsafe import Markup
        import sqlite3
        import pymupdf
        import tzdata
        required = (ASSET_ROOT / "templates" / "base.html", ASSET_ROOT / "static" / "css" / "style.css", ASSET_ROOT / "static" / "favicon.svg")
        if not all(path.is_file() for path in required):
            raise RuntimeError("Packaged templates or static assets are missing.")
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE VIRTUAL TABLE smoke_search USING fts5(text)")
            db.execute("INSERT INTO smoke_search VALUES ('Book OCR smoke')")
            assert db.execute("SELECT count(*) FROM smoke_search WHERE smoke_search MATCH 'Book'").fetchone()[0] == 1
        # Exercise delayed/bundled imports without constructing a Gemini client
        # or performing any network request.
        assert genai and tzdata and Environment().from_string("{{ value }}").render(value="ok") == "ok"
        assert str(Markup("Book-OCR")) == "Book-OCR"
        assert len(AESGCM.generate_key(bit_length=256)) == 32
        assert len(Document().paragraphs) == 0
        assert types.Part.from_bytes(data=b"offline-smoke", mime_type="image/png").inline_data.data == b"offline-smoke"
        with pymupdf.open() as document:
            document.new_page()
            assert len(document) == 1
        print(f"Book-OCR {version()} packaging smoke check passed.")
        return 0
    success, message = launch()
    if not success and getattr(sys, "frozen", False):
        try:
            from app.paths import DATA_ROOT
            log = DATA_ROOT / 'logs' / 'launcher.log'; log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text((log.read_text(encoding='utf-8')[-7000:] if log.exists() else '') + message + '\n', encoding='utf-8')
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, 'Book-OCR startup error', 0x10)
        except Exception: pass
    stream = sys.stdout if success else sys.stderr
    print(message, file=stream)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())

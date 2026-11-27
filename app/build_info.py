"""Capture checkout provenance at packaging time, or identify a source run."""
import subprocess
import sys
from datetime import datetime, timezone
from functools import lru_cache

from .paths import SOURCE_ROOT, version


def checkout_info():
    info = {"version": version(), "built_at": None, "commit": None, "fingerprint": None, "status": "development"}
    if not (SOURCE_ROOT / ".git").exists():
        return info

    def git(*args):
        return subprocess.check_output(
            ["git", "--no-optional-locks", *args], cwd=SOURCE_ROOT,
            stderr=subprocess.DEVNULL, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).decode("utf-8", errors="replace").strip()

    try:
        info["commit"] = git("rev-parse", "--verify", "HEAD")
        tags = git("tag", "--points-at", "HEAD").splitlines()
        if not git("status", "--porcelain", "--untracked-files=normal"):
            info["fingerprint"] = git("rev-parse", "HEAD^{tree}")
            if f"v{info['version']}" in tags:
                info["status"] = "release"
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def write_build_module(directory):
    info = checkout_info()
    info["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "_book_ocr_build.py").write_text(f"METADATA = {info!r}\n", encoding="utf-8")


@lru_cache(maxsize=1)
def running_build():
    if getattr(sys, "frozen", False):
        from _book_ocr_build import METADATA
        return METADATA
    return checkout_info()

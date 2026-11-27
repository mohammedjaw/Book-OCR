"""Read public GitHub release metadata on an explicit Settings request."""
import json
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

REPOSITORY = "https://github.com/mohammedjaw/Book-OCR"
RELEASES_API = "https://api.github.com/repos/mohammedjaw/Book-OCR/releases"


@dataclass(frozen=True)
class ReleaseCheck:
    message: str
    latest: str = ""
    prerelease: bool = False
    stable: str = ""


def _fetch(suffix):
    request = Request(RELEASES_API + suffix, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "Book-OCR",
    })
    with urlopen(request, timeout=5) as response:
        return json.load(response)


def _release(item):
    if (not isinstance(item, dict) or item.get("draft") is not False
            or not isinstance(item.get("prerelease"), bool)
            or not isinstance(item.get("tag_name"), str) or not item["tag_name"].strip()):
        raise ValueError("Invalid release metadata")
    return item["tag_name"], item["prerelease"]


def check_releases(installed):
    try:
        recent = _fetch("?per_page=1")
        if not isinstance(recent, list):
            raise ValueError("Invalid release list")
        if not recent:
            return ReleaseCheck("no_releases")
        latest, preview = _release(recent[0])
        try:
            stable, is_preview = _release(_fetch("/latest"))
        except HTTPError as exc:
            if exc.code == 404 and preview:
                return ReleaseCheck("no_stable", latest, True)
            raise
        if is_preview:
            raise ValueError("Expected a stable release")
        try:
            official, local = Version(stable), Version(installed)
            if official > local:
                message = "update_available"
            elif official == local:
                message = "version_current"
            else:
                message = "version_ahead"
        except InvalidVersion:
            message = "comparison_unavailable"
        return ReleaseCheck(message, latest, preview, stable)
    except (OSError, ValueError, HTTPException):
        return ReleaseCheck("update_check_failed")

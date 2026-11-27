import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import build_info, database, paths, releases, secrets
from app.routes import settings


class BuildInfoTests(unittest.TestCase):
    def test_only_clean_matching_tag_is_release(self):
        for tags, changes, expected in [
            ("v1.2.3", "", "release"), ("v1.2.3", " M main.py", "development"),
            ("v1.2.3", "?? app/new.py", "development"), ("v1.1.0", "", "development"),
        ]:
            with self.subTest(tags=tags, changes=changes), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / ".git").mkdir()
                answers = [b"a" * 40, tags.encode(), changes.encode(), b"b" * 40]
                with patch.object(build_info, "SOURCE_ROOT", root), patch.object(build_info, "version", return_value="1.2.3"), \
                     patch.object(build_info.subprocess, "check_output", side_effect=answers):
                    info = build_info.checkout_info()
                self.assertEqual(info["status"], expected)
                self.assertEqual(info["fingerprint"], None if changes else "b" * 40)
                self.assertIsNone(info["built_at"])

    def test_frozen_runtime_uses_generated_module_without_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("1.2.3")
            with patch.object(paths, "ASSET_ROOT", root), patch.object(build_info, "SOURCE_ROOT", root):
                build_info.write_build_module(root)
            spec = spec_from_file_location("_book_ocr_build", root / "_book_ocr_build.py")
            module = module_from_spec(spec)
            spec.loader.exec_module(module)
            (root / "VERSION").write_text("9.9.9")
            self.addCleanup(build_info.running_build.cache_clear)
            build_info.running_build.cache_clear()
            with patch.dict(sys.modules, _book_ocr_build=module), patch.object(sys, "frozen", True, create=True), \
                 patch.object(paths, "ASSET_ROOT", root), patch.object(build_info, "checkout_info", side_effect=AssertionError):
                info = build_info.running_build()
                self.assertEqual(info["version"], paths.version())
                self.assertEqual(info["version"], "1.2.3")
                self.assertIsNone(info["commit"])
                self.assertEqual(datetime.fromisoformat(info["built_at"]).utcoffset().total_seconds(), 0)


def release(tag, preview=False):
    return {"tag_name": tag, "prerelease": preview, "draft": False}


class ReleaseTests(unittest.TestCase):
    def test_separate_preview_and_numeric_stable_comparison(self):
        for local, message in [("0.2.9", "update_available"), ("0.2.10", "version_current"),
                               ("0.3.0", "version_ahead"), ("nightly", "comparison_unavailable")]:
            with self.subTest(local=local), patch.object(releases, "_fetch", side_effect=[
                [release("v0.3.0-rc.1", True)], release("v0.2.10"),
            ]):
                result = releases.check_releases(local)
                self.assertEqual(result, releases.ReleaseCheck(message, "v0.3.0-rc.1", True, "v0.2.10"))

    def test_preview_only_or_empty_repository(self):
        missing = HTTPError(releases.RELEASES_API, 404, "Not found", {}, None)
        with patch.object(releases, "_fetch", side_effect=[[release("v1rc1", True)], missing]):
            self.assertEqual(releases.check_releases("0.1").message, "no_stable")
        with patch.object(releases, "_fetch", return_value=[]):
            self.assertEqual(releases.check_releases("0.1").message, "no_releases")

    def test_offline_rate_limit_and_invalid_response(self):
        for response in [URLError("offline"), TimeoutError(), HTTPError("", 403, "", {}, None),
                         io.BytesIO(b"invalid json"), io.BytesIO(b'[{"draft":true}]')]:
            with self.subTest(response=response), patch.object(releases, "urlopen", side_effect=[response]):
                self.assertEqual(releases.check_releases("0.1").message, "update_check_failed")


class AboutSettingsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.enterContext(patch.object(database, "DB", root / "test.db"))
        self.enterContext(patch.object(secrets, "SECRETS_FILE", root / "secrets.json"))
        database.init_db()
        app = FastAPI()
        app.include_router(settings.router)
        self.client = self.enterContext(TestClient(app))

    def test_about_in_three_languages_and_both_themes_without_requests(self):
        with patch.object(releases, "urlopen", side_effect=AssertionError) as network:
            for lang, heading, direction in [("ar", "حول Book-OCR", "rtl"), ("en", "About Book-OCR", "ltr"),
                                             ("fa", "دربارهٔ Book-OCR", "rtl")]:
                for theme in ("فاتح", "داكن"):
                    html = self.client.post("/settings", data={"ui_language": lang, "theme": theme}).text
                    self.assertIn(f'lang="{lang}" dir="{direction}" data-theme="{theme}"', html)
                    self.assertIn(heading, html)
                    self.assertIn(paths.version(), html)
                    self.assertLess(html.index("/settings/keys/add"), html.index('id="about"'))
                    self.assertIn(releases.REPOSITORY, html)
            network.assert_not_called()

    def test_manual_check_redirects_and_refresh_is_offline(self):
        self.client.post("/settings", data={"ui_language": "en"})
        responses = [io.BytesIO(json.dumps(value).encode()) for value in
                     ([release("v8.1rc1", True)], release("v8.0"))]
        with patch.object(releases, "urlopen", side_effect=responses) as network:
            result = self.client.post("/settings/check-updates", follow_redirects=False)
            self.assertEqual(result.status_code, 303)
            self.assertEqual(result.headers["location"], "/settings#about")
            for _ in range(2):
                html = self.client.get("/settings").text
                self.assertIn("Prerelease", html)
                self.assertIn("v8.0", html)
                self.assertIn("v8.1rc1", html)
            self.assertEqual([call.args[0].full_url for call in network.call_args_list],
                             [releases.RELEASES_API + "?per_page=1", releases.RELEASES_API + "/latest"])

    def test_gemini_connection_test_keeps_about_section(self):
        from app.gemini_key_manager import add_key
        add_key("fixture", "mock-test-credential")
        with patch("google.genai.Client") as provider, patch.object(releases, "urlopen") as github:
            client = provider.return_value.__enter__.return_value
            client.models.list.return_value = iter(["fixture"])
            html = self.client.post("/settings/test").text
            client.models.list.assert_called_once()
            self.assertIn('id="about"', html)
            self.assertNotIn("mock-test-credential", html)
            github.assert_not_called()

    def test_connection_errors_distinguish_permissions_and_connectivity(self):
        from app.gemini_key_manager import add_key
        add_key("fixture", "mock-credential")
        self.client.post("/settings", data={"ui_language":"en"})
        for exc, expected in [(ConnectionError("mock-credential"), "connection problem"),
                              (RuntimeError("403 PERMISSION_DENIED"), "project permissions")]:
            with patch("google.genai.Client", side_effect=exc):
                html = self.client.post("/settings/test").text
                self.assertIn(expected, html)
                self.assertNotIn("mock-credential", html)

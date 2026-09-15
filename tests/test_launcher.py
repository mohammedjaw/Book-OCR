import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import launcher


class FakeProcess:
    def __init__(self, returncode=None, stderr_text=""):
        self.returncode = returncode
        self.stderr = __import__("io").StringIO(stderr_text)
        self.terminated = False
        self.killed = False

    def poll(self): return self.returncode
    def terminate(self): self.terminated = True; self.returncode = 0
    def wait(self, timeout=None): return self.returncode
    def kill(self): self.killed = True; self.returncode = 0


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_port_and_loopback_command(self):
        process = FakeProcess()
        with patch.object(launcher, "book_ocr_is_reachable", side_effect=[False, True]), patch.object(launcher, "port_is_available", return_value=True), patch.object(launcher, "start_server", return_value=process) as start:
            opened = []
            success, _ = launcher.launch(self.root, open_browser=opened.append)
        self.assertTrue(success)
        start.assert_called_once_with(self.root, 8765)
        self.assertEqual(opened[0], "http://book-ocr.localhost:8765")
        self.assertEqual(launcher.HOST, "127.0.0.1")

    def test_configured_port_is_used(self):
        config = self.root / "config" / "launcher.json"
        config.parent.mkdir()
        config.write_text(json.dumps({"port": 8767}), encoding="utf-8")
        process = FakeProcess()
        with patch.object(launcher, "book_ocr_is_reachable", side_effect=[False, True]), patch.object(launcher, "port_is_available", return_value=True), patch.object(launcher, "start_server", return_value=process) as start:
            opened = []
            success, _ = launcher.launch(self.root, open_browser=opened.append)
        self.assertTrue(success)
        start.assert_called_once_with(self.root, 8767)
        self.assertEqual(opened[0], "http://book-ocr.localhost:8767")

    def test_second_launch_opens_existing_instance_without_starting(self):
        opened = []
        with patch.object(launcher, "book_ocr_is_reachable", return_value=True), patch.object(launcher, "start_server") as start:
            success, _ = launcher.launch(self.root, open_browser=opened.append)
        self.assertTrue(success)
        start.assert_not_called()
        self.assertEqual(opened[0], "http://book-ocr.localhost:8765")

    def test_occupied_non_book_ocr_port_is_safe_error(self):
        with patch.object(launcher, "book_ocr_is_reachable", return_value=False), patch.object(launcher, "port_is_available", return_value=False), patch.object(launcher, "start_server") as start:
            success, message = launcher.launch(self.root)
        self.assertFalse(success)
        self.assertIn("port 8765 is already in use", message)
        start.assert_not_called()

    def test_failed_startup_never_opens_browser(self):
        process = FakeProcess(returncode=1, stderr_text="startup failed")
        opened = []
        with patch.object(launcher, "book_ocr_is_reachable", return_value=False), patch.object(launcher, "port_is_available", return_value=True), patch.object(launcher, "start_server", return_value=process):
            success, message = launcher.launch(self.root, open_browser=opened.append)
        self.assertFalse(success)
        self.assertEqual(opened, [])
        self.assertIn("startup failed", message)

    def test_interrupt_stops_only_started_server(self):
        process = FakeProcess()
        with patch.object(launcher, "book_ocr_is_reachable", return_value=False), patch.object(launcher, "port_is_available", return_value=True), patch.object(launcher, "start_server", return_value=process), patch.object(launcher, "wait_for_ready", side_effect=KeyboardInterrupt):
            success, message = launcher.launch(self.root)
        self.assertFalse(success)
        self.assertTrue(process.terminated)
        self.assertIn("cancelled", message)

    def test_project_icon_and_packaging_exclusions(self):
        project = Path(__file__).resolve().parents[1]
        self.assertTrue((project / "static" / "favicon.svg").is_file())
        source = (project / "launcher.py").read_text(encoding="utf-8")
        self.assertNotIn("data/", source)
        self.assertNotIn("books/", source)
        self.assertNotIn("secrets.json", source)

    def test_frozen_no_console_server_disables_uvicorn_log_config(self):
        with patch.object(launcher.sys, "frozen", True, create=True), \
             patch.object(launcher.sys, "argv", ["Book-OCR.exe", "--serve", "--port", "8877"]), \
             patch.object(launcher.sys, "stdout", None), patch.object(launcher.sys, "stderr", None), \
             patch("uvicorn.run") as run:
            self.assertEqual(launcher.main(), 0)
        run.assert_called_once_with("main:app", host="127.0.0.1", port=8877,
                                    log_level="warning", log_config=None)


if __name__ == "__main__":
    unittest.main()

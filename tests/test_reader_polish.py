"""Reader polish regression tests use disposable data and forbid Gemini calls."""
import hashlib
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import database, secrets
from app.routes import books, collections


class ReaderPolishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [
            patch.object(database, 'DB', self.root / 'library.db'),
            patch.object(secrets, 'SECRETS_FILE', self.root / 'secrets.json'),
            patch('google.genai.Client', side_effect=AssertionError('Gemini forbidden')),
        ]
        for item in self.patches:
            item.start()
        database.init_db()
        app = FastAPI()
        app.include_router(books.router)
        app.include_router(collections.router)
        self.client = TestClient(app)
        self.uid = str(uuid.uuid4())
        pdf_path = self.root / 'reader.pdf'
        with pymupdf.open() as pdf:
            for _ in range(3):
                pdf.new_page()
            pdf.save(pdf_path)
        with database.connect() as db:
            self.book_id = db.execute(
                "INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,3,'completed','','')",
                (self.uid, 'Reader book', 'reader.pdf', 'reader.pdf', str(pdf_path), hashlib.sha256(pdf_path.read_bytes()).hexdigest()),
            ).lastrowid
            for number in range(1, 4):
                db.execute(
                    "INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(?,?,'completed',?,'','')",
                    (self.book_id, number, f'line one page {number}\nline two'),
                )

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def test_toolbar_boundaries_routes_and_word_gate(self):
        first = self.client.get(f'/books/{self.uid}/pages/1').text
        self.assertNotIn(f'/pages/0', first)
        self.assertIn(f'/pages/2', first)
        self.assertIn(f'/file#page=1', first)
        self.assertIn(f'/text?page=1', first)
        self.assertIn(f'/export/docx', first)
        self.assertIn('id="copy-page"', first)
        last = self.client.get(f'/books/{self.uid}/pages/3').text
        self.assertNotIn(f'/pages/4', last)
        with database.connect() as db:
            db.execute("UPDATE book_pages SET status='pending' WHERE book_id=? AND page_number=3", (self.book_id,))
        self.assertNotIn('/export/docx', self.client.get(f'/books/{self.uid}/pages/2').text)

    def test_jump_validation_and_search_context(self):
        response = self.client.get(f'/books/{self.uid}/reader', params={'page': 2, 'q': 'line', 'mode': 'exact', 'book_id': self.book_id})
        self.assertEqual(response.status_code, 200)
        self.assertIn('value="2"', response.text)
        self.assertIn('q=line&amp;mode=exact&amp;book_id=', response.text)
        self.assertNotEqual(self.client.get(f'/books/{self.uid}/reader?page=0').status_code, 500)
        self.assertNotEqual(self.client.get(f'/books/{self.uid}/reader?page=999').status_code, 500)
        self.assertNotEqual(self.client.get(f'/books/{self.uid}/reader?page=bad').status_code, 500)

    def test_collection_breadcrumb_and_standalone(self):
        standalone = self.client.get(f'/books/{self.uid}/pages/2').text
        self.assertNotIn('reader-breadcrumb', standalone)
        collection_uid = str(uuid.uuid4())
        with database.connect() as db:
            collection_id = db.execute("INSERT INTO collections(uuid,title,created_at) VALUES(?,?,'')", (collection_uid, 'بحار الأنوار')).lastrowid
            db.execute('UPDATE books SET collection_id=?,volume_number=17 WHERE id=?', (collection_id, self.book_id))
        member = self.client.get(f'/books/{self.uid}/pages/2').text
        self.assertIn('reader-breadcrumb', member)
        self.assertIn(f'/collections/{collection_uid}', member)
        self.assertIn('بحار الأنوار', member)
        self.assertIn('17', member)

    def test_language_theme_markup_and_copy_script(self):
        for language, direction in (('ar', 'rtl'), ('fa', 'rtl'), ('en', 'ltr')):
            for theme in ('فاتح', 'داكن', 'تلقائي'):
                with database.connect() as db:
                    db.execute("UPDATE settings SET value=? WHERE key='ui_language'", (language,))
                    db.execute("INSERT INTO settings(key,value) VALUES('theme',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (theme,))
                html = self.client.get(f'/books/{self.uid}/pages/1').text
                self.assertIn(f'dir="{direction}"', html)
                self.assertIn(f'data-theme="{theme}"', html)
                self.assertIn('aria-label=', html)
        script = Path('static/js/ocr-copy.js').read_text(encoding='utf-8')
        self.assertIn("text.textContent", script)
        self.assertIn("window.addEventListener('scroll'", script)
        self.assertIn("window.innerWidth", script)


if __name__ == '__main__':
    unittest.main()

"""Offline regressions: every mutable path is temporary; Gemini is forbidden."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import database, secrets, gemini_key_manager as keys, ocr_service
from app.export_service import make_text
from app.routes import books, collections, settings


class PartialExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [patch.object(database, 'DB', root/'library.db'), patch.object(secrets, 'SECRETS_FILE', root/'secrets.json'), patch.object(keys, 'REQUEST_INTERVAL', 0), patch('google.genai.Client', side_effect=AssertionError('Live Gemini forbidden'))]
        for p in self.patches: p.start()
        keys._next_request = 0
        database.init_db()
        with database.connect() as db:
            db.execute("INSERT INTO collections VALUES(1,'collection','Collection','')")
            db.execute("INSERT INTO books(id,book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at,collection_id,volume_number) VALUES(1,'book','Arabic','a.pdf','a.pdf','unused','hash',4,'paused','','',1,1)")
            for n in (4,2,1):
                db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(1,?,'completed',?,'','')",(n,f'أَصل الصفحة {n}\n  محفوظ  '))
            db.execute("UPDATE book_pages SET status='failed',extracted_text=NULL WHERE page_number=2")
        app = FastAPI()
        for module in (books,collections,settings): app.include_router(module.router)
        self.client = TestClient(app)

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def dump(self):
        with database.connect() as db: return '\n'.join(db.iterdump())

    def test_states_unicode_order_placeholders_and_no_writes(self):
        for status in ('paused','running','keys_unavailable','completed'):
            with self.subTest(status=status):
                with database.connect() as db: db.execute('UPDATE books SET status=?',(status,))
                before = self.dump()
                for ext in ('md','txt'):
                    result = self.client.get(f'/books/book/export/{ext}')
                    self.assertEqual(result.status_code,200)
                    text=result.content.decode('utf-8')
                    self.assertIn('INCOMPLETE',text)
                    self.assertIn('completed: 2; failed: 1; pending: 0; processing: 0; missing: 1',text)
                    self.assertIn('أَصل الصفحة 1\n  محفوظ  ',text)
                    self.assertIn('Page 2: extraction status=failed',text)
                    self.assertIn('Page 3: extraction status=missing',text)
                    self.assertLess(text.index('Page 1'),text.index('Page 2'))
                    self.assertLess(text.index('Page 3'),text.index('Page 4'))
                self.assertEqual(before,self.dump())

    def test_completed_and_repeat_export(self):
        with database.connect() as db:
            db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(1,3,'completed','جديد','','')")
            db.execute("UPDATE book_pages SET status='completed',extracted_text='نجاح' WHERE page_number=2")
        text=self.client.get('/books/book/export/txt').text
        self.assertNotIn('INCOMPLETE',text)
        self.assertIn('جديد',text)
        self.assertIn('completed: 4',text)
        # Existing completed formats and package checks remain reachable.
        self.assertEqual(self.client.get('/books/book/export/json').status_code,200)
        self.assertEqual(self.client.get('/books/book/export/docx').status_code,200)

    def test_collection_and_unavailable(self):
        self.assertEqual(self.client.get('/collections/collection/export/md').status_code,200)
        self.assertEqual(self.client.get('/books/absent/export/txt').status_code,404)
        with database.connect() as db: db.execute("UPDATE book_pages SET status='pending',extracted_text=NULL")
        self.assertEqual(self.client.get('/books/book/export/txt').status_code,409)
        self.assertEqual(self.client.get('/collections/collection/export/txt').status_code,409)

    def test_selection_save_reload_exhausted_active_and_live_refresh(self):
        keys.add_key('exhausted','fake-a'); keys.add_key('available','fake-b')
        a,b=[k['id'] for k in keys.list_keys()]
        keys.record_request(a,success=False,status='quota_exhausted')
        response=self.client.post('/settings',data={'ocr_key_mode':'pool','pool_present':'1','pool_ids':b})
        self.assertEqual(response.status_code,200)
        self.assertEqual(ocr_service.current_key_selection(),('pool',[b]))
        key=keys.acquire_key('single',[],selection_provider=ocr_service.current_key_selection)
        self.assertEqual(key['id'],b)
        # No cached pool is allowed to select a key unchecked in persisted settings.
        self.client.post('/settings',data={'ocr_key_mode':'pool','pool_present':'1'})
        with self.assertRaises(keys.KeysUnavailable):
            keys.acquire_key('pool',[b],selection_provider=ocr_service.current_key_selection)

    def test_mocked_quota_switch_preserves_completed_pages(self):
        import pymupdf
        pdf=Path(self.tmp.name)/'test.pdf'
        with pymupdf.open() as document:
            for _ in range(4): document.new_page()
            document.save(pdf)
        keys.add_key('exhausted','fake-a'); keys.add_key('available','fake-b')
        ids=[k['id'] for k in keys.list_keys()]
        with database.connect() as db:
            db.execute('UPDATE books SET file_path=?',(str(pdf),))
            db.execute("INSERT INTO book_pages(book_id,page_number,status,created_at,updated_at) VALUES(1,3,'pending','','')")
            db.execute("UPDATE settings SET value='pool' WHERE key='ocr_key_mode'")
            db.execute("UPDATE settings SET value=? WHERE key='ocr_pool_ids'",(json.dumps(ids),))
            before=[tuple(r) for r in db.execute("SELECT * FROM book_pages WHERE status='completed'")]
        with patch.object(ocr_service,'generate',side_effect=[Exception('429 requests_per_day'), 'نجاح جديد']) as generate:
            self.assertTrue(ocr_service.extract_page(1,3))
            self.assertEqual([call.args[0] for call in generate.call_args_list],['fake-a','fake-b'])
            self.assertFalse(ocr_service.extract_page(1,1))
            self.assertEqual(generate.call_count,2)
        with database.connect() as db:
            self.assertEqual(before,[tuple(r) for r in db.execute("SELECT * FROM book_pages WHERE page_number IN (1,4)")])

    def test_snapshot_during_concurrent_completion(self):
        import sqlite3
        from app import export_service
        with database.connect() as db: db.execute('PRAGMA journal_mode=WAL')
        original=export_service.connect
        class ConcurrentReader:
            def __enter__(self):
                self.db=original(); return self
            def execute(self,sql,args=()):
                result=self.db.execute(sql,args)
                if sql.startswith('SELECT * FROM books'):
                    # The first SELECT establishes the snapshot before a writer commits.
                    book=result.fetchall()
                    with database.connect() as writer:
                        writer.execute("UPDATE book_pages SET status='completed',extracted_text='later' WHERE page_number=2")
                    class Result:
                        def fetchone(inner): return book[0]
                    return Result()
                return result
            def __exit__(self,*args): return self.db.__exit__(*args)
        with patch.object(export_service,'connect',side_effect=ConcurrentReader):
            path,_=make_text('book','txt')
        try:
            self.assertIn('status=failed',Path(path).read_text(encoding='utf-8'))
            self.assertNotIn('later',Path(path).read_text(encoding='utf-8'))
        finally: Path(path).unlink()

    def test_daily_reset_and_invalid_key(self):
        keys.add_key('a','fake-a'); a=keys.list_keys()[0]['id']
        keys.record_request(a,success=False,status='quota_exhausted')
        with self.assertRaises(keys.KeysUnavailable): keys.acquire_key('pool',[a])
        with patch.object(keys,'_day',return_value='2099-01-01'):
            self.assertEqual(keys.acquire_key('pool',[a])['id'],a)
            keys.record_request(a,success=False,status='invalid_key')
        with patch.object(keys,'_day',return_value='2099-01-02'):
            with self.assertRaises(keys.KeysUnavailable): keys.acquire_key('pool',[a])

if __name__ == '__main__': unittest.main()

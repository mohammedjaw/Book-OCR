"""Synthetic-only transfer and selection regressions; Gemini is forbidden."""
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile

import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import database, secrets, book_manager, package_service, ocr_service, ocr_worker
from app import gemini_key_manager as keys
from app.routes import books, settings, transfer


class IncompletePackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(database,'DB',self.root/'source.db'),
                        patch.object(secrets,'SECRETS_FILE',self.root/'secrets.json'),
                        patch.object(book_manager,'BOOKS',self.root/'books'),
                        patch.object(keys,'REQUEST_INTERVAL',0),
                        patch('google.genai.Client',side_effect=AssertionError('Live Gemini forbidden'))]
        for item in self.patches: item.start()
        keys._next_request = 0
        database.init_db()
        book_manager.BOOKS.mkdir()
        self.uid = str(uuid.uuid4())
        self.pdf = book_manager.BOOKS/'synthetic.pdf'
        with pymupdf.open() as doc:
            for _ in range(5): doc.new_page(width=60,height=60)
            doc.save(self.pdf)
        self.text = 'أَصل محفوظ\n  العربية كما هي  '
        with database.connect() as db:
            self.bid = db.execute('INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,5,?,?,?)',
                (self.uid,'Synthetic incomplete','synthetic.pdf',self.pdf.name,str(self.pdf),hashlib.sha256(self.pdf.read_bytes()).hexdigest(),'keys_unavailable','created','updated')).lastrowid
            for n,(status,text) in enumerate([('completed',self.text),('pending',None),('failed','retained unfinished text'),('processing',None),('completed','')],1):
                pid=db.execute('INSERT INTO book_pages(book_id,page_number,status,extracted_text,line_count,model,thinking_level,error_kind,error_message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (self.bid,n,status,text,2 if n==1 else 0 if n==5 else None,'model','minimal','service_error' if status=='failed' else None,'sanitized error' if status=='failed' else None,'created','updated')).lastrowid
                if status=='completed': db.execute('INSERT INTO page_search VALUES(?,?,?)',(pid,text,text))
        app=FastAPI()
        for module in (books,settings,transfer): app.include_router(module.router)
        self.client=TestClient(app)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def dump(self):
        with database.connect() as db: return '\n'.join(db.iterdump())

    def export(self):
        path,_=package_service.export_package(self.uid)
        self.addCleanup(lambda:Path(path).unlink(missing_ok=True))
        return Path(path).read_bytes()

    def members(self,blob):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            return {name:archive.read(name) for name in archive.namelist()}

    def mutate(self,blob,change):
        members=self.members(blob)
        manifest=json.loads(members['manifest.json']); pages=json.loads(members['pages.json'])
        change(manifest,pages)
        members['manifest.json']=json.dumps(manifest).encode()
        members['pages.json']=json.dumps(pages).encode()
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            for name,value in members.items(): archive.writestr(name,value)
        return stream.getvalue()

    @contextmanager
    def recipient(self):
        with patch.object(database,'DB',self.root/'recipient.db'),patch.object(book_manager,'BOOKS',self.root/'recipient-books'):
            database.init_db()
            yield

    def test_v2_roundtrip_preserves_pdf_text_status_metadata_and_no_source_writes(self):
        before=self.dump(); original=self.pdf.read_bytes();blob=self.export()
        self.assertEqual(before,self.dump());self.assertEqual(original,self.pdf.read_bytes())
        members=self.members(blob);manifest=json.loads(members['manifest.json'])
        self.assertEqual(manifest['format_version'],2)
        self.assertEqual(manifest['resume_policy'],'processing_to_pending')
        self.assertEqual(members['original.pdf'],original)
        self.assertEqual([p['status'] for p in json.loads(members['pages.json'])],['completed','pending','failed','processing','completed'])
        with self.recipient():
            self.assertEqual(package_service.import_package(io.BytesIO(blob)),self.uid)
            with database.connect() as db:
                book=db.execute('SELECT * FROM books').fetchone()
                rows=db.execute('SELECT * FROM book_pages ORDER BY page_number').fetchall()
                self.assertEqual(book['status'],'paused')
                self.assertEqual(Path(book['file_path']).read_bytes(),original)
                self.assertEqual([r['page_number'] for r in rows],[1,2,3,4,5])
                self.assertEqual([r['status'] for r in rows],['completed','pending','failed','pending','completed'])
                self.assertEqual(rows[0]['extracted_text'],self.text)
                self.assertEqual(rows[2]['extracted_text'],'retained unfinished text')
                self.assertEqual((rows[2]['error_kind'],rows[2]['error_message']),('service_error','sanitized error'))
                self.assertEqual((rows[0]['line_count'],rows[0]['created_at'],rows[0]['updated_at']),(2,'created','updated'))
                self.assertEqual(db.execute('SELECT count(*) FROM page_search').fetchone()[0],2)
                self.assertFalse(ocr_worker.active(book['id']))

    def test_imported_pages_resume_without_reprocessing_completed_text(self):
        blob=self.export()
        with self.recipient():
            package_service.import_package(io.BytesIO(blob));keys.add_key('Synthetic','fake-key')
            with patch.object(ocr_service,'generate',return_value='mock new result') as mock:
                self.assertFalse(ocr_service.extract_page(1,1))
                self.assertTrue(ocr_service.extract_page(1,2))
                self.assertTrue(ocr_service.extract_page(1,4))
                self.assertEqual(mock.call_count,2)
            with database.connect() as db:
                rows=db.execute('SELECT status,extracted_text FROM book_pages ORDER BY page_number').fetchall()
                self.assertEqual(tuple(rows[0]),('completed',self.text))
                self.assertEqual(rows[2]['status'],'failed')
                self.assertEqual(tuple(rows[4]),('completed',''))

    def test_complete_exports_remain_v1_and_old_v1_imports(self):
        with database.connect() as db: db.execute("UPDATE book_pages SET status='completed',extracted_text=?",(self.text,))
        blob=self.export();members=self.members(blob)
        self.assertEqual(json.loads(members['manifest.json'])['format_version'],1)
        self.assertNotIn('resume_policy',json.loads(members['manifest.json']))
        with self.recipient():
            package_service.import_package(io.BytesIO(blob))
            with database.connect() as db:
                self.assertEqual(db.execute('SELECT status FROM books').fetchone()[0],'completed')
                self.assertEqual(db.execute("SELECT count(*) FROM book_pages WHERE status='completed'").fetchone()[0],5)

    def test_duplicate_uuid_or_pdf_never_overwrites(self):
        blob=self.export();before=self.dump();pdf=self.pdf.read_bytes()
        for candidate in (blob,self.mutate(blob,lambda m,p:m.update(book_uuid=str(uuid.uuid4())))):
            with self.assertRaises(ValueError): package_service.import_package(io.BytesIO(candidate))
            self.assertEqual(before,self.dump());self.assertEqual(pdf,self.pdf.read_bytes())
            self.assertEqual(list(book_manager.BOOKS.glob('*.pdf')),[self.pdf])

    def test_invalid_v2_and_partial_v1_are_rejected_before_storage(self):
        blob=self.export()
        changes=[lambda m,p:m.update(format_version=3),lambda m,p:m.update(format_version=1),
                 lambda m,p:m.update(resume_policy='unsupported'),lambda m,p:p.reverse(),
                 lambda m,p:p[0].update(extracted_text=None),lambda m,p:p[1].update(status='unknown'),
                 lambda m,p:p[1].update(extracted_text=17),lambda m,p:p[1].update(line_count=-1),
                 lambda m,p:p[1].update(error_kind={}),lambda m,p:m.update(sha256='wrong')]
        with self.recipient():
            before=self.dump()
            for change in changes:
                with self.subTest(change=change),self.assertRaises(ValueError):
                    package_service.import_package(io.BytesIO(self.mutate(blob,change)))
                self.assertEqual(before,self.dump())
                self.assertFalse(book_manager.BOOKS.exists() and list(book_manager.BOOKS.iterdir()))

    def test_import_rolls_back_database_and_pdf_on_index_failure(self):
        blob=self.export()
        with self.recipient():
            before=self.dump()
            with patch.object(package_service,'normalize_arabic',side_effect=ValueError('forced failure')):
                with self.assertRaises(ValueError):package_service.import_package(io.BytesIO(blob))
            self.assertEqual(before,self.dump())
            self.assertEqual(list(book_manager.BOOKS.iterdir()),[])

    def test_incomplete_route_and_import_route_are_accessible(self):
        response=self.client.get(f'/books/{self.uid}/export/package')
        self.assertEqual(response.status_code,200)
        self.assertEqual(json.loads(self.members(response.content)['manifest.json'])['format_version'],2)
        html=self.client.get(f'/books/{self.uid}').text
        self.assertIn(f'/books/{self.uid}/export/package',html)
        with self.recipient():
            response=self.client.post('/transfer/import',files={'file':('synthetic.bookocr.zip',response.content,'application/zip')},follow_redirects=False)
            self.assertEqual(response.status_code,303)

    def test_missing_page_records_fail_without_silent_omission(self):
        with database.connect() as db:db.execute('DELETE FROM book_pages WHERE page_number=2')
        before=self.dump()
        self.assertEqual(self.client.get(f'/books/{self.uid}/export/package').status_code,409)
        self.assertEqual(before,self.dump())

    def test_683_page_324_completed_synthetic_roundtrip(self):
        pdf=self.root/'683-synthetic.pdf'
        with pymupdf.open() as doc:
            for _ in range(683):doc.new_page(width=30,height=30)
            doc.save(pdf)
        with database.connect() as db:
            db.execute('DELETE FROM page_search')
            db.execute('DELETE FROM book_pages')
            db.execute('UPDATE books SET page_count=683,file_path=?,stored_filename=?,file_hash=?',
                       (str(pdf),pdf.name,hashlib.sha256(pdf.read_bytes()).hexdigest()))
            for n in range(1,684):
                db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (self.bid,n,'completed' if n<=324 else 'pending',f'نص اختباري {n}\n  محفوظ  ' if n<=324 else None,'',''))
        blob=self.export()
        with self.recipient():
            package_service.import_package(io.BytesIO(blob))
            with database.connect() as db:
                self.assertEqual(dict(db.execute('SELECT status,count(*) FROM book_pages GROUP BY status')),{'completed':324,'pending':359})
                self.assertEqual(db.execute('SELECT extracted_text FROM book_pages WHERE page_number=324').fetchone()[0],'نص اختباري 324\n  محفوظ  ')
                self.assertEqual(db.execute('SELECT created_at,updated_at FROM book_pages WHERE page_number=1').fetchone()[:],('',''))
                self.assertEqual(db.execute('SELECT status FROM books').fetchone()[0],'paused')
                self.assertEqual(db.execute('SELECT count(*) FROM page_search').fetchone()[0],324)

    def test_changed_pool_is_saved_in_pool_mode_without_js(self):
        keys.add_key('One','fake-one');keys.add_key('Two','fake-two')
        a,b=[k['id'] for k in keys.list_keys()]
        credential_bytes=secrets.SECRETS_FILE.read_bytes()
        self.client.post('/settings',data={'ocr_key_mode':'single','pool_present':'1','pool_ids':a})
        self.assertEqual(ocr_service.current_key_selection(),('pool',[a]))
        self.client.post('/settings',data={'ocr_key_mode':'single','pool_present':'1','pool_ids':a})
        self.assertEqual(ocr_service.current_key_selection(),('single',[a]))
        self.client.post('/settings',data={'ocr_key_mode':'single','pool_present':'1','pool_ids':b})
        self.assertEqual(ocr_service.current_key_selection(),('pool',[b]))
        self.assertEqual(secrets.SECRETS_FILE.read_bytes(),credential_bytes)

    def test_export_uses_snapshot_during_concurrent_page_completion(self):
        with database.connect() as db:db.execute('PRAGMA journal_mode=WAL')
        original=package_service.connect
        class Reader:
            def __enter__(self):self.db=original();return self
            def execute(self,sql,args=()):
                result=self.db.execute(sql,args)
                if sql.startswith('SELECT * FROM books'):
                    row=result.fetchone()
                    with database.connect() as writer:writer.execute("UPDATE book_pages SET status='completed',extracted_text='newer' WHERE page_number=2")
                    class Result:
                        def fetchone(inner):return row
                    return Result()
                return result
            def __exit__(self,*args):return self.db.__exit__(*args)
        with patch.object(package_service,'connect',side_effect=Reader):blob=self.export()
        pages=json.loads(self.members(blob)['pages.json'])
        self.assertEqual(pages[1]['status'],'pending');self.assertIsNone(pages[1]['extracted_text'])


if __name__=='__main__':unittest.main()

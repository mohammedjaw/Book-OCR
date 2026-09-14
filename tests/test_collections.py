"""Collections tests use temporary storage and forbid any Gemini client."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch
import pymupdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import database, secrets, book_manager, package_service
from app.search_service import normalize_arabic, search_pages, count_pages
from app.routes import books, collections, search

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(database,'DB',self.root/'library.db'),
            patch.object(secrets,'SECRETS_FILE',self.root/'secrets.json'),
            patch.object(book_manager,'BOOKS',self.root),
            patch('google.genai.Client',side_effect=AssertionError('Gemini forbidden'))]
        for p in self.patches: p.start()
        database.init_db()
        secrets.save_secrets({'gemini_api_key':'FULL-SECRET-MUST-NOT-RENDER'})
        app=FastAPI()
        for module in (books,collections,search): app.include_router(module.router)
        self.client=TestClient(app)
        self.ids=[]
        for n in range(4):
            uid=str(uuid.uuid4()); pdf_path=self.root/f'{uid}.pdf'
            with pymupdf.open() as pdf:
                for _ in range(n+1): pdf.new_page()
                pdf.save(pdf_path)
            with database.connect() as db:
                bid=db.execute("INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'completed','before','before')",(uid,f'Volume {n} متن فارسی',f'original-{n}.pdf',pdf_path.name,str(pdf_path),hashlib.sha256(pdf_path.read_bytes()).hexdigest(),n+1)).lastrowid
                for page in range(1,n+2):
                    text=f'common أَصل محفوظ book {n} page {page}'
                    pid=db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(?,?,'completed',?,'before','before')",(bid,page,text)).lastrowid
                    db.execute('INSERT INTO page_search VALUES(?,?,?)',(pid,text,normalize_arabic(text)))
            self.ids.append((bid,uid))
        self.before=self.snapshot()

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def snapshot(self):
        with database.connect() as db:
            return ([tuple(r) for r in db.execute('SELECT id,book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at FROM books ORDER BY id')],
                    [tuple(r) for r in db.execute('SELECT * FROM book_pages ORDER BY id')],
                    {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.glob('*.pdf')})

    def create(self,title='بحار الأنوار'):
        response=self.client.post('/collections',data={'title':title},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        uid=response.headers['location'].split('/')[-1]
        with database.connect() as db: cid=db.execute('SELECT id FROM collections WHERE uuid=?',(uid,)).fetchone()[0]
        return cid,uid

    def assign(self,uid,book_index,number):
        response=self.client.post(f'/books/{self.ids[book_index][1]}/collection',data={'collection_id':uid,'volume_number':number},follow_redirects=False)
        self.assertEqual(response.status_code,303)

    def test_collection_lifecycle_and_data_preservation(self):
        cid,uid=self.create()
        for i,number in enumerate((3,1,2)): self.assign(uid,i,number)
        html=self.client.get('/books').text
        self.assertEqual(html.count(f'data-collection="{uid}"'),1)
        for _,book_uid in self.ids[:3]: self.assertNotIn(f'data-book="{book_uid}"',html)
        self.assertIn(f'data-book="{self.ids[3][1]}"',html)
        html=self.client.get(f'/collections/{uid}').text
        positions=[html.index(f'data-book="{self.ids[i][1]}"') for i in (1,2,0)]
        self.assertEqual(positions,sorted(positions))
        self.assign(uid,0,1)
        self.assertEqual(self.client.post(f'/collections/{uid}/rename',data={'title':'Renamed <safe>'}).status_code,200)
        self.assertIn('Renamed &lt;safe&gt;',self.client.get(f'/collections/{uid}').text)
        self.assertEqual(self.client.post(f'/collections/{uid}/delete').status_code,409)
        with database.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM collections WHERE id=?',(cid,))
        for _,book_uid in self.ids[:3]:
            self.assertEqual(self.client.post(f'/books/{book_uid}/collection',data={}).status_code,200)
            self.assertIn(f'data-book="{book_uid}"',self.client.get('/books').text)
        self.assertEqual(self.client.post(f'/collections/{uid}/delete').status_code,200)
        self.assertEqual(self.client.get(f'/collections/{uid}').status_code,404)
        self.assertEqual(self.snapshot(),self.before)

    def test_scoped_fts_and_physical_links(self):
        cid,uid=self.create()
        for i in range(3): self.assign(uid,i,i+1)
        other,other_uid=self.create('Other collection')
        self.assign(other_uid,3,1)
        for mode,q in [('exact','common'),('flexible','اصل')]:
            rows=search_pages(q,mode,collection_id=cid)
            self.assertEqual({r['book_id'] for r in rows},{b for b,_ in self.ids[:3]})
            self.assertEqual(len(rows),6)
            self.assertEqual(count_pages(q,mode,collection_id=cid),6)
        self.assertEqual(count_pages('common'),10)
        self.assertEqual(count_pages('common',book_id=self.ids[3][0]),4)
        self.assertEqual(count_pages('common',collection_id=99999),0)
        response=self.client.get('/search',params={'q':'common','book_id':f'collection:{cid}'})
        self.assertEqual(response.status_code,200)
        self.assertIn('بحار الأنوار',response.text)
        self.assertIn(f'value="collection:{cid}" selected',response.text)
        self.assertNotIn(f'value="{self.ids[0][0]}"',response.text)
        self.assertNotIn(f'/books/{self.ids[3][1]}/pages/',response.text)
        for bid,book_uid in self.ids[:3]:
            url=f'/books/{book_uid}/pages/1?q=common&book_id=collection:{cid}'
            self.assertIn(f'/books/{book_uid}/pages/1?',response.text)
            reader=self.client.get(url)
            self.assertEqual(reader.status_code,200)
            self.assertIn('/file#page=1',reader.text)
            self.assertIn(f'book_id=collection:{cid}',reader.text)
            self.assertNotIn(f'/books/{self.ids[3][1]}/pages/',reader.text)
        self.client.post(f'/books/{self.ids[3][1]}/collection',data={})
        filtered=self.client.get('/search',params={'q':'common','book_id':self.ids[3][0]})
        self.assertIn(f'/books/{self.ids[3][1]}/pages/4?',filtered.text)
        self.assertNotIn(f'/books/{self.ids[0][1]}/pages/',filtered.text)
        self.assertEqual(self.snapshot(),self.before)

    def test_pagination_keeps_scope(self):
        cid,uid=self.create();self.assign(uid,0,1)
        with database.connect() as db:
            for number in range(2,32):
                pid=db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(?,?,'completed','common','','')",(self.ids[0][0],number)).lastrowid
                db.execute("INSERT INTO page_search VALUES(?,'common','common')",(pid,))
        html=self.client.get('/search',params={'q':'common','book_id':f'collection:{cid}','page':2}).text
        self.assertIn(f'book_id=collection:{cid}&page=1',html)
        self.assertEqual(html.count('class="search-snippet"'),6)

    def test_delete_one_member_preserves_siblings(self):
        cid,uid=self.create()
        for i in range(3): self.assign(uid,i,i+1)
        victim=self.ids[1][1]
        self.assertEqual(self.client.post(f'/books/{victim}/delete',data={'confirm':victim}).status_code,200)
        self.assertFalse((self.root/f'{victim}.pdf').exists())
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM books WHERE collection_id=?',(cid,)).fetchone()[0],2)
        for index in (0,2):
            self.assertEqual(self.client.get(f'/books/{self.ids[index][1]}').status_code,200)
            self.assertEqual(hashlib.sha256((self.root/f'{self.ids[index][1]}.pdf').read_bytes()).hexdigest(),self.before[2][f'{self.ids[index][1]}.pdf'])
        self.assertEqual(count_pages('common',collection_id=cid),4)

    def test_languages_themes_and_no_secrets(self):
        cid,uid=self.create('بحار الأنوار / مجموعه فارسی / Collection')
        self.assign(uid,0,1)
        for lang,direction in [('ar','rtl'),('fa','rtl'),('en','ltr')]:
            for theme in ('فاتح','داكن','تلقائي'):
                with database.connect() as db:
                    db.execute("UPDATE settings SET value=? WHERE key='ui_language'",(lang,))
                    db.execute("INSERT OR REPLACE INTO settings VALUES('theme',?)",(theme,))
                for url in ['/books',f'/collections/{uid}',f'/books/{self.ids[0][1]}',f'/search?q=common&book_id=collection:{cid}']:
                    response=self.client.get(url)
                    self.assertEqual(response.status_code,200)
                    self.assertIn(f'lang="{lang}" dir="{direction}"',response.text)
                    self.assertIn(f'data-theme="{theme}"',response.text)
                    self.assertNotIn('FULL-SECRET-MUST-NOT-RENDER',response.text)

    def test_validation_and_integrity(self):
        cid,uid=self.create()
        for title in (' ','x'*501): self.assertEqual(self.client.post('/collections',data={'title':title}).status_code,400)
        for value in ('collection:no','bad','-1','999999999999999999999999'):
            self.assertEqual(self.client.get('/search',params={'book_id':value}).status_code,400)
        self.assertEqual(self.client.post(f'/books/{self.ids[0][1]}/collection',data={'collection_id':'missing'}).status_code,404)
        for number in (-1,0,2147483648):
            self.assertEqual(self.client.post(f'/books/{self.ids[0][1]}/collection',data={'collection_id':uid,'volume_number':number}).status_code,400)
        with database.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError): db.execute('UPDATE books SET collection_id=999 WHERE id=?',(self.ids[0][0],))
        self.assertEqual(self.snapshot(),self.before)

    def test_package_remains_individual(self):
        cid,uid=self.create();self.assign(uid,0,1)
        response=self.client.get(f'/books/{self.ids[0][1]}/export/package')
        self.assertEqual(response.status_code,200)
        import io
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertNotIn('collection_id',manifest)
            self.assertEqual(manifest['book_uuid'],self.ids[0][1])
            self.assertEqual(hashlib.sha256(archive.read('original.pdf')).hexdigest(),self.before[2][f'{self.ids[0][1]}.pdf'])
        # Import into a second disposable library using the unmodified package API.
        from starlette.datastructures import UploadFile
        with patch.object(database,'DB',self.root/'import.db'),patch.object(book_manager,'BOOKS',self.root/'imported'):
            (self.root/'imported').mkdir();database.init_db()
            imported=package_service.import_package(io.BytesIO(response.content))
            with database.connect() as db:
                row=db.execute('SELECT * FROM books').fetchone()
                self.assertEqual(row['book_uuid'],self.ids[0][1]);self.assertIsNone(row['collection_id'])
                self.assertEqual(db.execute('SELECT extracted_text FROM book_pages').fetchone()[0],self.before[1][0][4])

class MigrationTests(unittest.TestCase):
    def test_legacy_additive_migration_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(database,'DB',Path(tmp)/'legacy.db'):
                with database.connect() as db:
                    db.execute('CREATE TABLE books (id INTEGER PRIMARY KEY,book_uuid TEXT,title TEXT,page_count INTEGER)')
                    db.execute("INSERT INTO books VALUES(1,'original-uuid','Original',17)")
                    db.commit()
                    database.init_collections(db);database.init_collections(db)
                    self.assertEqual(tuple(db.execute('SELECT * FROM books').fetchone()),(1,'original-uuid','Original',17,None,None))
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM collections').fetchone()[0],0)

if __name__=='__main__': unittest.main()

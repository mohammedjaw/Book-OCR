import tempfile
import unittest
import time
import uuid
from pathlib import Path
from unittest.mock import patch
import pymupdf
from app import database, secrets, gemini_key_manager as keys, ocr_worker as worker, ocr_service as ocr

class StabilizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(database, 'DB', self.root/'test.db'), patch.object(secrets, 'SECRETS_FILE', self.root/'secrets.json'), patch.object(keys, 'REQUEST_INTERVAL', 0), patch('google.genai.Client', side_effect=AssertionError('Real Gemini access forbidden in tests'))]
        for p in self.patches: p.start()
        keys._next_request = 0
        database.init_db()
        keys.add_key('One', 'test-secret-1111')
        keys.add_key('Two', 'test-secret-2222')
        self.uid = str(uuid.uuid4())
        self.pdf = self.root/'book.pdf'
        with pymupdf.open() as pdf:
            for _ in range(8): pdf.new_page()
            pdf.save(self.pdf)
        with database.connect() as db:
            self.bid = db.execute("INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,8,'ready','','')", (self.uid,'Test','book.pdf','book.pdf',str(self.pdf),'hash')).lastrowid
            db.executemany("INSERT INTO book_pages(book_id,page_number,created_at,updated_at) VALUES(?,?,'','')", [(self.bid,n) for n in range(1,9)])
    def tearDown(self):
        worker.pause(self.bid)
        self.wait()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()
    def wait(self):
        deadline=time.monotonic()+10
        while worker.active(self.bid) and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(worker.active(self.bid))
    def counts(self):
        with database.connect() as db: return dict(db.execute('SELECT status,COUNT(*) FROM book_pages GROUP BY status'))
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routes import books,settings,search,transfer,home
        app=FastAPI()
        for module in (books,settings,search,transfer,home): app.include_router(module.router)
        return TestClient(app)
    def complete(self):
        with patch.object(ocr,'generate',return_value='أَصل\nexact text <script>literal</script>'):
            worker.start(self.bid); self.wait()
    def test_completion_and_counters(self):
        with patch.object(ocr,'generate',return_value='أَصل\nexact text') as mock:
            self.assertTrue(worker.start(self.bid)); self.wait()
            self.assertEqual(mock.call_count,8)
            worker.start(self.bid);self.wait();self.assertEqual(mock.call_count,8)
        self.assertEqual(self.counts(),{'completed':8})
        self.assertEqual(keys.list_keys()[0]['requests'],8)
        self.assertEqual(keys.list_keys()[0]['successes'],8)
    def test_quota_preserves_pending(self):
        with patch.object(ocr,'generate',side_effect=Exception('429 daily quota')):
            worker.start(self.bid);self.wait()
        self.assertEqual(self.counts(),{'pending':8})
        self.assertEqual(keys.list_keys()[0]['last_status'],'quota_exhausted')
    def test_pool_failover(self):
        with database.connect() as db:
            db.execute("UPDATE settings SET value='pool' WHERE key='ocr_key_mode'")
            import json
            db.execute("UPDATE settings SET value=? WHERE key='ocr_pool_ids'",(json.dumps([k['id'] for k in keys.list_keys()]),))
        def generate(key,*args):
            if key.endswith('1111'): raise Exception('daily quota')
            return 'safe'
        with patch.object(ocr,'generate',side_effect=generate): worker.start(self.bid);self.wait()
        self.assertEqual(self.counts(),{'completed':8})
    def test_restart_and_classification(self):
        with database.connect() as db: db.execute("UPDATE book_pages SET status='processing' WHERE page_number=1")
        worker.recover_stale();self.assertEqual(self.counts(),{'pending':8})
        import httpx
        for error in (httpx.ReadTimeout(''),httpx.ConnectError(''),httpx.ReadError('')):
            self.assertEqual(ocr.classify_gemini_error(error),'network_error')
        for error, kind in [('429 RESOURCE_EXHAUSTED','rate_limited'),('503','service_error'),('401','invalid_key'),('400 bad request','permanent_request')]:
            self.assertEqual(ocr.classify_gemini_error(Exception(error)),kind)
    def test_permanent_and_retry(self):
        with patch.object(ocr,'generate',side_effect=Exception('400 bad request')):
            worker.start(self.bid);self.wait()
        self.assertEqual(self.counts(),{'failed':8})
        with patch.object(ocr,'generate') as mock:
            worker.start(self.bid,retry_failed=True);self.wait();mock.assert_not_called()

    def test_settings_persistence_and_secrets(self):
        client=self.client()
        selected=keys.list_keys()[1]['id']
        response=client.post('/settings',data={'ui_language':'en','theme':'فاتح','font_family':'Arial','font_size':'25','line_height':'2','model':'gemini-3.1-flash-lite','thinking':'low','concurrency':'2','active_key_id':selected,'ocr_key_mode':'pool','pool_present':'1','pool_ids':selected})
        self.assertEqual(response.status_code,200)
        self.assertNotIn('test-secret-',response.text)
        for theme in ('داكن','تلقائي','فاتح'):
            client.post('/settings',data={'theme':theme})
            database.init_db()  # additive initialization must retain saved preferences
            html=client.get('/books').text
            self.assertIn(f'data-theme="{theme}"',html)
            self.assertIn('lang="en" dir="ltr"',html)
        with database.connect() as db: values=dict(db.execute('SELECT * FROM settings'))
        self.assertEqual(values['font_family'],'Arial');self.assertEqual(values['font_size'],'25')
        self.assertEqual(values['thinking_level'],'low');self.assertEqual(values['max_concurrent_pages'],'2')
        self.assertEqual(values['ocr_key_mode'],'pool');self.assertIn(selected,values['ocr_pool_ids'])
        self.assertEqual(keys.get_active_key()['id'],selected)
        for lang in ('ar','fa'):
            client.post('/settings',data={'ui_language':lang})
            self.assertIn(f'lang="{lang}" dir="rtl"',client.get('/settings').text)
    def test_routes_reader_search_exports(self):
        client=self.client()
        self.assertEqual(client.get(f'/books/{self.uid}/export/package').status_code,409)
        self.complete()
        for path in ('','/pages','/reader?page=1','/view?page=8','/text','/file','/download/pdf','/pages?status=processing','/delete'):
            with self.subTest(path=path): self.assertEqual(client.get(f'/books/{self.uid}{path}').status_code,200)
        self.assertEqual(client.get(f'/books/{self.uid}/pages/0').status_code,404)
        self.assertEqual(client.get('/books/missing/ocr/status').status_code,404)
        html=client.get(f'/books/{self.uid}/pages/1').text
        self.assertIn('/file#page=1',html); self.assertNotIn('/pages/0',html)
        self.assertIn('&lt;script&gt;literal&lt;/script&gt;',html)
        self.assertIn('name="page"',html)
        for extension in ('json','docx','package'):
            self.assertEqual(client.get(f'/books/{self.uid}/export/{extension}').status_code,200)
        from app.search_service import search_pages,highlight_text
        self.assertEqual(len(search_pages('أَصل','exact')),8)
        self.assertEqual(len(search_pages('اصل','flexible')),8)
        self.assertEqual(len(search_pages('أَصل','flexible')),8)
        self.assertEqual(len(search_pages('nonexistent: (','exact')),0)
        self.assertEqual(str(highlight_text('text','َ','flexible')),'text')
        self.assertEqual(client.get('/search',params={'q':'اصل','mode':'flexible'}).status_code,200)
        data=client.get(f'/books/{self.uid}/ocr/status').json()
        self.assertTrue(data['complete']);self.assertFalse(data['active'])

    def test_failed_page_rerender_retry_is_fresh_full_page_and_isolated(self):
        client=self.client()
        with database.connect() as db:
            page_id=db.execute("SELECT id FROM book_pages WHERE book_id=? AND page_number=3",(self.bid,)).fetchone()[0]
            before={r['page_number']:tuple(r) for r in db.execute("SELECT page_number,status,extracted_text,error_kind,error_message FROM book_pages WHERE book_id=?",(self.bid,))}
            db.execute("UPDATE book_pages SET status='failed',error_kind='service_error',error_message='old diagnostic' WHERE id=?",(page_id,))
        self.assertNotIn('rerender-retry',client.get(f'/books/{self.uid}/pages/2').text)
        failed_html=client.get(f'/books/{self.uid}/pages/3').text
        self.assertIn(f'/books/{self.uid}/pages/3/rerender-retry',failed_html)
        self.assertIn('إعادة إنشاء الصفحة من PDF وإعادة الاستخراج',failed_html)

        real_open=pymupdf.open
        opened=[]; rendered=[]
        def tracked_open(*args,**kwargs):
            opened.append((args,kwargs)); return real_open(*args,**kwargs)
        def fake_generate(key,image,model,thinking,**kwargs):
            pix=pymupdf.Pixmap(image); rendered.append((pix.width,pix.height))
            return 'fresh retry text'
        with patch.object(ocr.pymupdf,'open',side_effect=tracked_open),patch.object(ocr,'generate',side_effect=fake_generate) as gemini_stub:
            response=client.post(f'/books/{self.uid}/pages/3/rerender-retry',follow_redirects=False)
            self.assertEqual(response.status_code,303);self.wait()
        self.assertEqual(gemini_stub.call_count,1)
        self.assertEqual(rendered,[(1488,2105)])  # Entire default A4 media box at the normal 2.5x scale.
        self.assertEqual(len([call for call in opened if call[0] and Path(call[0][0]) == self.pdf]),1)
        with database.connect() as db:
            row=db.execute("SELECT id,page_number,status,extracted_text,error_kind,error_message FROM book_pages WHERE id=?",(page_id,)).fetchone()
            self.assertEqual(tuple(row),(page_id,3,'completed','fresh retry text',None,None))
            self.assertEqual(db.execute("SELECT exact_text FROM page_search WHERE page_id=?",(page_id,)).fetchone()[0],'fresh retry text')
            after={r['page_number']:tuple(r) for r in db.execute("SELECT page_number,status,extracted_text,error_kind,error_message FROM book_pages WHERE book_id=?",(self.bid,))}
        self.assertEqual({n:v for n,v in before.items() if n != 3},{n:v for n,v in after.items() if n != 3})

        with database.connect() as db:
            db.execute("UPDATE book_pages SET status='failed',error_kind='service_error',error_message='old again' WHERE id=?",(page_id,))
        with patch.object(ocr,'generate',side_effect=Exception('400 secret provider payload')) as gemini_stub:
            self.assertEqual(client.post(f'/books/{self.uid}/pages/3/rerender-retry',follow_redirects=False).status_code,303);self.wait()
        self.assertEqual(gemini_stub.call_count,1)
        with database.connect() as db:
            failed=db.execute("SELECT id,page_number,status,error_kind,error_message FROM book_pages WHERE id=?",(page_id,)).fetchone()
            others=db.execute("SELECT COUNT(*) FROM book_pages WHERE book_id=? AND page_number!=3 AND status!='pending'",(self.bid,)).fetchone()[0]
        self.assertEqual(tuple(failed),(page_id,3,'failed','permanent_request','permanent_request'))
        self.assertEqual(others,0)
        self.assertNotIn('secret provider payload',failed['error_message'])
        self.assertEqual(client.post(f'/books/{self.uid}/pages/2/rerender-retry').status_code,409)
    def test_package_roundtrip_and_validation(self):
        import json,zipfile,io
        from app import book_manager,package_service
        self.complete()
        package,_=package_service.export_package(self.uid)
        self.addCleanup(lambda:Path(package).unlink(missing_ok=True))
        with zipfile.ZipFile(package) as z: members={name:z.read(name) for name in z.namelist()}
        self.assertEqual(set(members),{'manifest.json','pages.json','original.pdf'})
        self.assertEqual(members['original.pdf'],self.pdf.read_bytes())
        self.assertNotIn(b'test-secret',members['manifest.json']+members['pages.json'])
        target_db=self.root/'import.db'; target_books=self.root/'import-books'
        def archive(data):
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as z:
                for name,value in data.items(): z.writestr(name,value)
            stream.seek(0);return stream
        with patch.object(database,'DB',target_db),patch.object(book_manager,'BOOKS',target_books):
            database.init_db()
            for mutation in ('hash','order','uuid','count','version','text','traversal'):
                bad=dict(members); manifest=json.loads(bad['manifest.json']);pages=json.loads(bad['pages.json'])
                if mutation=='hash': manifest['sha256']='wrong'
                if mutation=='order': pages.reverse()
                if mutation=='uuid': manifest['book_uuid']='../../outside'
                if mutation=='count': manifest['page_count']=9
                if mutation=='version': manifest['format_version']=2
                if mutation=='text': pages[0]['extracted_text']=None
                if mutation=='traversal': bad['../outside']=b'bad'
                bad['manifest.json']=json.dumps(manifest).encode();bad['pages.json']=json.dumps(pages).encode()
                with self.assertRaises(ValueError):package_service.import_package(archive(bad))
                with database.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM books').fetchone()[0],0)
            imported=package_service.import_package(archive(members));self.assertEqual(imported,self.uid)
            with database.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM page_search').fetchone()[0],8)
                self.assertEqual(db.execute('SELECT extracted_text FROM book_pages LIMIT 1').fetchone()[0],'أَصل\nexact text <script>literal</script>')
            self.assertEqual(self.client().get(f'/books/{self.uid}/reader?page=8').status_code,200)
    def test_delete_confirmation_and_isolation(self):
        from app import book_manager
        self.complete(); client=self.client()
        unrelated=self.root/'unrelated.pdf';unrelated.write_bytes(b'keep')
        self.assertEqual(client.post(f'/books/{self.uid}/delete').status_code,400)
        self.assertTrue(self.pdf.exists())
        with patch.object(book_manager,'BOOKS',self.root):
            self.assertEqual(client.post(f'/books/{self.uid}/delete',data={'confirm':self.uid}).status_code,200)
        self.assertFalse(self.pdf.exists());self.assertEqual(unrelated.read_bytes(),b'keep')
        with database.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM page_search').fetchone()[0],0)
    def test_pause_drains_and_resume(self):
        from threading import Event
        entered=Event();release=Event()
        def generate(*args): entered.set();release.wait(3);return 'preserved'
        with patch.object(ocr,'generate',side_effect=generate):
            worker.start(self.bid);self.assertTrue(entered.wait(3))
            self.assertFalse(worker.start(self.bid));worker.pause(self.bid)
            self.assertEqual(worker.state(self.bid),'pausing')
            release.set();self.wait()
        counts=self.counts();self.assertGreater(counts.get('pending',0),0)
        completed=counts.get('completed',0)
        with patch.object(ocr,'generate',return_value='remaining') as mock:
            worker.start(self.bid);self.wait();self.assertEqual(mock.call_count,8-completed)
    def test_transient_retry_and_exhaustion(self):
        from threading import Event
        for error in (TimeoutError('timeout'),Exception('500'),Exception('503')):
            with self.subTest(error=error),patch.object(ocr,'generate',side_effect=[error,'retained']),patch.object(Event,'wait',return_value=False):
                self.assertTrue(ocr.extract_page(self.bid,1))
            with database.connect() as db:db.execute("UPDATE book_pages SET status='pending' WHERE page_number=1")
        with patch.object(ocr,'generate',side_effect=Exception('503')),patch.object(Event,'wait',return_value=False):
            self.assertFalse(ocr.extract_page(self.bid,1))
        self.assertEqual(self.counts(),{'failed':1,'pending':7})
        with patch.object(ocr,'generate',return_value='retry'):
            worker.start(self.bid,retry_failed=True);self.wait()
        self.assertEqual(self.counts(),{'completed':1,'pending':7})
    def test_quota_day_reset_and_atomic_counters(self):
        from concurrent.futures import ThreadPoolExecutor
        key=keys.list_keys()[0]['id']
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda _:keys.record_request(key),range(100)))
        self.assertEqual(keys.list_keys()[0]['requests'],100)
        keys.record_request(key,False,'quota_exhausted')
        with patch.object(keys,'_day',return_value='2099-01-01'):
            value=keys.list_keys()[0]
            self.assertEqual(value['requests'],0);self.assertEqual(value['last_status'],'available')
    def test_rate_limited_key_is_temporary(self):
        key=keys.list_keys()[0]['id']
        keys.record_request(key,False,'rate_limited',cooldown=10)
        with patch.object(keys.time,'time',return_value=time.time()+20):
            self.assertEqual(keys.acquire_key('single',[])['id'],key)
        self.assertEqual(ocr.classify_gemini_error(Exception('429 RESOURCE_EXHAUSTED')),'rate_limited')

    def test_463_pages_no_duplicate_processing(self):
        from threading import Lock
        total=463
        with pymupdf.open() as pdf:
            for _ in range(total):pdf.new_page(width=36,height=36)
            pdf.save(self.root/'long.pdf')
        with database.connect() as db:
            db.execute('UPDATE books SET page_count=?,file_path=? WHERE id=?',(total,str(self.root/'long.pdf'),self.bid))
            db.executemany("INSERT INTO book_pages(book_id,page_number,created_at,updated_at) VALUES(?,?,'','')",[(self.bid,n) for n in range(9,total+1)])
            db.execute("UPDATE settings SET value='5' WHERE key='max_concurrent_pages'")
        current=set();seen=[];guard=Lock();extract=ocr.extract_page;peak=0
        def track(book_id,number,stop):
            nonlocal peak
            with guard:
                self.assertNotIn(number,current);current.add(number);seen.append(number);peak=max(peak,len(current))
            try:return extract(book_id,number,stop)
            finally:
                with guard:current.remove(number)
        with patch.object(worker,'extract_page',side_effect=track),patch.object(ocr,'generate',return_value='unchanged'):
            worker.start(self.bid)
            deadline=time.monotonic()+60
            while worker.active(self.bid) and time.monotonic()<deadline:time.sleep(.05)
            self.assertFalse(worker.active(self.bid))
        self.assertEqual(self.counts(),{'completed':total});self.assertEqual(len(set(seen)),total);self.assertEqual(len(seen),total)
        self.assertLessEqual(peak,5)
    def test_startup_lock_and_recovery(self):
        from app.lifecycle import library_lock
        from fastapi.testclient import TestClient
        import main
        with database.connect() as db:
            db.execute("UPDATE book_pages SET status='completed',extracted_text='preserved' WHERE page_number=1")
            db.execute("UPDATE book_pages SET status='processing' WHERE page_number=2")
        with TestClient(main.app) as client:
            self.assertEqual(client.get('/books').status_code,200)
            with self.assertRaises(RuntimeError):
                with library_lock(database.DB.with_suffix('.lock')):pass
        self.assertEqual(self.counts(),{'completed':1,'pending':7})
        with database.connect() as db:self.assertEqual(db.execute('SELECT extracted_text FROM book_pages WHERE page_number=1').fetchone()[0],'preserved')
    def test_import_transaction_rolls_back_index_failure(self):
        from app import package_service,book_manager
        self.complete();package,_=package_service.export_package(self.uid)
        self.addCleanup(lambda:Path(package).unlink(missing_ok=True))
        folder=self.root/'new-books'
        with patch.object(database,'DB',self.root/'new.db'),patch.object(book_manager,'BOOKS',folder):
            database.init_db()
            with patch.object(package_service,'normalize_arabic',side_effect=ValueError('forced index failure')):
                with self.assertRaises(ValueError):package_service.import_package(package)
            with database.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM books').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM book_pages').fetchone()[0],0)
            self.assertEqual(list(folder.iterdir()),[])
    def test_single_key_and_invalid_pool(self):
        import json
        selected=keys.list_keys()[1]['id'];keys.set_active_key(selected)
        with patch.object(ocr,'generate',return_value='single') as mock:ocr.extract_page(self.bid,1)
        self.assertTrue(mock.call_args.args[0].endswith('2222'))
        with database.connect() as db:
            db.execute("UPDATE settings SET value='pool' WHERE key='ocr_key_mode'")
            db.execute("UPDATE settings SET value=? WHERE key='ocr_pool_ids'",(json.dumps([k['id'] for k in keys.list_keys()]),))
        with patch.object(ocr,'generate',side_effect=Exception('401 INVALID API KEY')):
            worker.start(self.bid);self.wait()
        self.assertEqual(self.counts(),{'completed':1,'pending':7})
        self.assertTrue(all(k['last_status']=='invalid_key' for k in keys.list_keys()))
    def test_delete_refuses_external_path(self):
        self.assertEqual(self.client().post(f'/books/{self.uid}/delete',data={'confirm':self.uid}).status_code,409)
        self.assertTrue(self.pdf.exists())
    def test_backoff_respects_provider_hint(self):
        error=Exception('429 retry in 45s')
        self.assertGreaterEqual(ocr.retry_delay(error,0),45)
        self.assertGreaterEqual(ocr.retry_delay(Exception('503'),2),16)
    def test_settings_forms_not_nested(self):
        from html.parser import HTMLParser
        class Forms(HTMLParser):
            depth=0
            nested=False
            def handle_starttag(self,tag,attrs):
                if tag=='form':
                    self.depth+=1
                    self.nested |= self.depth>1
            def handle_endtag(self,tag):
                if tag=='form':self.depth-=1
        parser=Forms();parser.feed(self.client().get('/settings').text)
        self.assertFalse(parser.nested);self.assertEqual(parser.depth,0)

    def test_pacing_and_pool_cooldown(self):
        clock=[100000.0]
        def advance(seconds):clock[0]+=seconds
        first=keys.list_keys()[0]['id'];second=keys.list_keys()[1]['id']
        with patch.object(keys,'REQUEST_INTERVAL',2),patch.object(keys.time,'time',side_effect=lambda:clock[0]),patch.object(keys.time,'sleep',side_effect=advance):
            a=keys.acquire_key('pool',[first,second]);start=clock[0]
            b=keys.acquire_key('pool',[first,second])
            self.assertNotEqual(a['id'],b['id']);self.assertGreaterEqual(clock[0]-start,2)
            keys.record_request(first,False,'rate_limited',cooldown=30)
            self.assertEqual(keys.acquire_key('pool',[first,second])['id'],second)
    def test_previous_day_outcome_does_not_exhaust_new_day(self):
        key=keys.list_keys()[0]['id'];day=keys.record_request(key)
        with patch.object(keys,'_day',return_value='2099-01-01'):
            keys.record_request(key,False,'quota_exhausted',request_day=day)
            item=keys.list_keys()[0];self.assertEqual(item['requests'],0);self.assertEqual(item['failures'],0)
            self.assertEqual(item['last_status'],'available')
    def test_delete_crash_restores_referenced_pdf(self):
        from app import book_manager
        parked=self.pdf.with_name(self.pdf.name+'.deleting');self.pdf.rename(parked)
        with patch.object(book_manager,'BOOKS',self.root):book_manager.recover_interrupted_deletions()
        self.assertTrue(self.pdf.exists());self.assertFalse(parked.exists())

    def test_temporary_429_retries_without_quota_pause(self):
        with patch.object(ocr,'generate',side_effect=[Exception('429 RESOURCE_EXHAUSTED'),'success']),patch.object(ocr,'retry_delay',return_value=0):
            self.assertTrue(ocr.extract_page(self.bid,1))
        item=keys.list_keys()[0]
        self.assertEqual((item['requests'],item['successes'],item['failures']),(2,1,1))
        self.assertEqual(item['last_status'],'available')
        self.assertEqual(self.counts(),{'completed':1,'pending':7})
    def test_delete_keeps_other_book_records(self):
        from app import book_manager
        other=self.root/'other.pdf';other.write_bytes(self.pdf.read_bytes())
        with database.connect() as db:
            other_id=db.execute("INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,1,'completed','','')",(str(uuid.uuid4()),'Other','other.pdf','other.pdf',str(other),'other-hash')).lastrowid
            page_id=db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(?,1,'completed','other text','','')",(other_id,)).lastrowid
            db.execute("INSERT INTO page_search VALUES(?,'other text','other text')",(page_id,))
        with patch.object(book_manager,'BOOKS',self.root):
            self.assertEqual(self.client().post(f'/books/{self.uid}/delete',data={'confirm':self.uid}).status_code,200)
        self.assertTrue(other.exists())
        with database.connect() as db:
            self.assertEqual(db.execute('SELECT extracted_text FROM book_pages WHERE book_id=?',(other_id,)).fetchone()[0],'other text')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM page_search').fetchone()[0],1)

if __name__=='__main__': unittest.main()

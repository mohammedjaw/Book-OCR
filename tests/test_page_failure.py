import tempfile, unittest, uuid
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
import pymupdf
from app import database, secrets, gemini_key_manager as keys, ocr_service

class PageFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        self.patches=[patch.object(database,'DB',root/'db'),patch.object(secrets,'SECRETS_FILE',root/'secrets.json'),patch.object(keys,'REQUEST_INTERVAL',0),patch.object(ocr_service,'retry_delay',return_value=0)]
        for p in self.patches:p.start()
        keys._next_request=0; database.init_db(); keys.add_key('A','key-a'); keys.add_key('B','key-b'); keys.add_key('C','key-c')
        pdf=root/'a.pdf'
        with pymupdf.open() as doc:
            for n in range(2): doc.new_page().insert_text((72,72), f'Normal page {n}')
            doc.save(pdf)
        self.uid=str(uuid.uuid4())
        with database.connect() as db:
            self.bid=db.execute("INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at) VALUES(?,?,?,?,?,?,2,'ready','','')",(self.uid,'x','a.pdf','a.pdf',str(pdf),'hash')).lastrowid
            db.executemany("INSERT INTO book_pages(book_id,page_number,created_at,updated_at) VALUES(?,?,'','')",[(self.bid,1),(self.bid,2)])
            db.execute("UPDATE settings SET value='pool' WHERE key='ocr_key_mode'")
            import json; db.execute("UPDATE settings SET value=? WHERE key='ocr_pool_ids'",(json.dumps([k['id'] for k in keys.list_keys()]),))
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def replace_pdf(self, draw):
        pdf=Path(self.tmp.name)/'content.pdf'
        with pymupdf.open() as doc:
            page=doc.new_page()
            draw(page)
            doc.save(pdf)
        with database.connect() as db:
            db.execute('UPDATE books SET file_path=? WHERE id=?',(str(pdf),self.bid))

    def assert_normal_ocr_path(self, draw, result):
        self.replace_pdf(draw)
        calls=[]
        def fake(key,image,model,thinking,**kwargs):
            calls.append((image,kwargs.get('mime_type','image/png')))
            return result
        with patch.object(ocr_service,'generate',side_effect=fake):
            self.assertTrue(ocr_service.extract_page(self.bid,1))
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1],'image/png')
        with pymupdf.open(stream=calls[0][0],filetype='png') as rendered:
            self.assertEqual(rendered.page_count,1)
        with database.connect() as db:
            row=db.execute("SELECT status,extracted_text FROM book_pages WHERE page_number=1").fetchone()
            self.assertEqual(tuple(row),('completed',result))

    def test_blank_looking_page_uses_normal_ocr_path(self):
        self.assert_normal_ocr_path(lambda page: None,'')

    def test_one_word_page_uses_normal_ocr_path(self):
        self.assert_normal_ocr_path(lambda page: page.insert_text((72,72),'word'),'word')

    def test_dense_page_uses_normal_ocr_path(self):
        def draw(page):
            for y in range(40,800,10): page.insert_text((30,y),'dense historical text ' * 7,fontsize=6)
        self.assert_normal_ocr_path(draw,'recognized ' * 5000)

    def test_503_waits_across_keys_and_retries_the_same_page(self):
        class Overloaded(Exception):
            code = 503

        with database.connect() as db:
            db.execute("UPDATE book_pages SET status='completed', extracted_text='keep me' WHERE page_number=1")
            saved = tuple(db.execute("SELECT * FROM book_pages WHERE page_number=1").fetchone())

        now = 1000
        calls = []
        stop = Event()
        def send(key, image, model, thinking):
            calls.append((now, image))
            if len(calls) <= 6:
                raise Overloaded('temporary connection failure')
            return 'page two'

        def advance_clock(seconds):
            nonlocal now
            self.assertGreater(seconds, 0)
            # Another worker with another key must also wait at the scheduler.
            with patch.object(other_worker, 'wait', return_value=True), self.assertRaises(keys.SchedulingPaused):
                keys.acquire_key('single', [], other_worker)
            now = keys._next_request
            return False

        other_worker = Event()
        with patch.object(keys, 'time', SimpleNamespace(time=lambda: now)), \
             patch.object(stop, 'wait', side_effect=advance_clock), \
             patch.object(ocr_service, 'generate', side_effect=send):
            self.assertTrue(ocr_service.extract_page(self.bid, 2, stop))
        times = [t for t, _ in calls]
        self.assertEqual([b-a for a, b in zip(times, times[1:])], [30, 60, 120, 240, 300, 300])
        self.assertTrue(all(image is calls[0][1] for _, image in calls))
        self.assertEqual(sum(k['failures'] for k in keys.list_keys()), 6)
        with database.connect() as db:
            self.assertEqual(tuple(db.execute("SELECT * FROM book_pages WHERE page_number=1").fetchone()), saved)
            self.assertEqual(tuple(db.execute("SELECT status,extracted_text FROM book_pages WHERE page_number=2").fetchone()), ('completed', 'page two'))

    def test_pause_during_503_wait_leaves_page_resumable(self):
        stop = Event()
        def pause(seconds):
            stop.set()
            return True
        with patch.object(ocr_service, 'generate', side_effect=Exception('503 UNAVAILABLE')) as send, \
             patch.object(stop, 'wait', side_effect=pause), patch.object(keys, 'time', SimpleNamespace(time=lambda: 1000)), \
             patch.object(ocr_service, 'retry_delay', return_value=90):
            with self.assertRaises(keys.SchedulingPaused):
                ocr_service.extract_page(self.bid, 1, stop)
            self.assertEqual(keys._next_request, 1090)
            send.assert_called_once()
        with database.connect() as db:
            self.assertEqual(tuple(db.execute("SELECT status,extracted_text FROM book_pages WHERE page_number=1").fetchone()), ('pending', None))
        with patch.object(ocr_service, 'generate', return_value='resumed') as send:
            self.assertTrue(ocr_service.extract_page(self.bid, 1))
            send.assert_called_once()

    def test_503_during_fallback_retries_identical_image(self):
        for stage in ('image/png', 'image/jpeg'):
            with self.subTest(stage=stage):
                sequence = [Exception('500 internal'), Exception('500 internal')]
                if stage == 'image/jpeg':
                    sequence.append(ConnectionError('connection lost'))
                sequence += [Exception('503 UNAVAILABLE'), 'recovered']
                stop = Event()
                start_time = 1000 if stage == 'image/png' else 2000
                now = start_time
                def wait(seconds):
                    nonlocal now
                    now += seconds
                    return False
                with patch.object(keys, 'time', SimpleNamespace(time=lambda: now)), \
                     patch.object(stop, 'wait', side_effect=wait), \
                     patch.object(ocr_service, 'generate', side_effect=sequence) as send:
                    keys._next_request = 0
                    page = 1 if stage == 'image/png' else 2
                    self.assertTrue(ocr_service.extract_page(self.bid, page, stop))
                first, retry = send.call_args_list[-2:]
                self.assertEqual(first.kwargs['mime_type'], stage)
                self.assertEqual(first.kwargs, retry.kwargs)
                self.assertIs(first.args[1], retry.args[1])
                self.assertEqual(now, start_time + 30)
    def test_fallback_completes_page_after_two_keys(self):
        calls=[]
        def fake(key,image,model,thinking,**kwargs):
            calls.append((key,len(image)))
            if len(calls)<3: raise Exception('500 provider')
            return 'fallback text'
        with patch.object(ocr_service,'generate',side_effect=fake), patch.object(ocr_service,'MAX_ATTEMPTS',8):
            self.assertTrue(ocr_service.extract_page(self.bid,1))
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM book_pages WHERE page_number=1").fetchone()[0],'completed')
        self.assertGreaterEqual(len(calls),3)

    def test_jpeg_fallback_completes(self):
        calls=[]
        def fake(key,image,model,thinking,**kwargs):
            calls.append(kwargs.get('mime_type','image/png'))
            if len(calls) < 4: raise Exception('500 provider')
            return 'jpeg text'
        with patch.object(ocr_service,'generate',side_effect=fake), patch.object(ocr_service,'MAX_ATTEMPTS',8):
            self.assertTrue(ocr_service.extract_page(self.bid,1))
        self.assertIn('image/jpeg',calls)

    def test_exhausted_fallback_pool_leaves_page_pending(self):
        errors = [Exception('500'), Exception('500'), Exception('429 requests_per_day'),
                  Exception('401'), Exception('429 requests_per_day')]
        with patch.object(ocr_service, 'generate', side_effect=errors), self.assertRaises(ocr_service.KeysUnavailable):
            ocr_service.extract_page(self.bid, 1)
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM book_pages WHERE page_number=1").fetchone()[0], 'pending')

    def test_missing_response_text_is_a_service_failure(self):
        with patch('google.genai.Client') as provider:
            provider.return_value.__enter__.return_value.models.generate_content.return_value.text = None
            with self.assertRaises(ocr_service.EmptyOCRResponse) as error:
                ocr_service.generate('mock-credential', b'image', 'model', 'minimal')
            self.assertEqual(ocr_service.classify_gemini_error(error.exception), 'service_error')

    def test_split_fallback_is_disabled(self):
        calls=[]
        def fake(key,image,model,thinking,**kwargs):
            calls.append(kwargs.get('mime_type','image/png'))
            raise Exception('500 provider')
        with patch.object(ocr_service,'generate',side_effect=fake), patch.object(ocr_service,'MAX_ATTEMPTS',8):
            self.assertFalse(ocr_service.extract_page(self.bid,1))
        with database.connect() as db:
            self.assertIsNone(db.execute("SELECT extracted_text FROM book_pages WHERE page_number=1").fetchone()[0])
        self.assertEqual(calls.count('image/jpeg'),1)

    def test_blank_fallback_is_sent_to_gemini_normally(self):
        blank=self.tmp.name + '/blank.pdf'
        with pymupdf.open() as doc: doc.new_page(); doc.save(blank)
        with database.connect() as db: db.execute('UPDATE books SET file_path=? WHERE id=?',(blank,self.bid))
        responses=[Exception('500 provider'),Exception('500 provider'),'']
        with patch.object(ocr_service,'generate',side_effect=responses) as mocked, patch.object(ocr_service,'MAX_ATTEMPTS',8):
            self.assertTrue(ocr_service.extract_page(self.bid,1))
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT status,extracted_text FROM book_pages WHERE page_number=1").fetchone()[0:2],('completed',''))
        self.assertEqual(mocked.call_count,3)

    def test_sparse_page_long_result_is_not_rejected_by_length(self):
        pdf=self.tmp.name + '/near.pdf'
        with pymupdf.open() as doc:
            page=doc.new_page(); page.draw_rect(pymupdf.Rect(10,10,30,30),color=(0,0,0),fill=(0,0,0)); doc.save(pdf)
        with database.connect() as db: db.execute('UPDATE books SET file_path=? WHERE id=?',(pdf,self.bid))
        def fake(*args,**kwargs):
            if fake.calls < 2: fake.calls += 1; raise Exception('500 provider')
            return 'invented ' * 200
        fake.calls=0
        with patch.object(ocr_service,'generate',side_effect=fake), patch.object(ocr_service,'MAX_ATTEMPTS',8):
            self.assertTrue(ocr_service.extract_page(self.bid,1))
        with database.connect() as db:
            row=db.execute("SELECT status,extracted_text,error_kind FROM book_pages WHERE page_number=1").fetchone()
            self.assertEqual(tuple(row),('completed','invented ' * 200,None))
    def test_fallback_failure_marks_only_page_and_next_page_continues(self):
        with patch.object(ocr_service,'generate',side_effect=Exception('500 provider')), patch.object(ocr_service,'MAX_ATTEMPTS',8):
            self.assertFalse(ocr_service.extract_page(self.bid,1))
        with database.connect() as db:
            row=db.execute("SELECT status,error_kind FROM book_pages WHERE page_number=1").fetchone()
            self.assertEqual(tuple(row),('failed','page_service_failure'))
            self.assertEqual(db.execute("SELECT status FROM book_pages WHERE page_number=2").fetchone()[0],'pending')
        self.assertTrue(all(k['last_status'] not in ('quota_exhausted','invalid_key') for k in keys.list_keys()))
        with patch.object(ocr_service,'generate',return_value='next page'):
            self.assertTrue(ocr_service.extract_page(self.bid,2))
        with database.connect() as db:
            self.assertEqual(db.execute("SELECT status,extracted_text FROM book_pages WHERE page_number=2").fetchone()[0:2],('completed','next page'))

    def test_failure_diagnostics_are_sanitized_and_stage_specific(self):
        class ProviderError(Exception):
            code = 500
            response = type('Response', (), {'status_code': 500, 'headers': {'retry-after': '7'}})()
        calls = []
        failures = [ProviderError('secret-api-key'), Exception('500 internal'), TimeoutError('timeout'), ConnectionError('network'), Exception('jpeg provider')]
        def fake(key, image, model, thinking, **kwargs):
            calls.append(kwargs.get('mime_type', 'image/png'))
            item = failures.pop(0)
            if isinstance(item, Exception): raise item
            return item
        with patch.object(ocr_service,'generate',side_effect=fake), patch.object(ocr_service,'MAX_ATTEMPTS',8):
            self.assertFalse(ocr_service.extract_page(self.bid,1))
        with database.connect() as db:
            row=db.execute("SELECT status,error_kind,error_message FROM book_pages WHERE page_number=1").fetchone()
        self.assertEqual(row['status'],'failed')
        self.assertEqual(row['error_kind'],'page_service_failure')
        message=row['error_message']
        self.assertIn('category=service_error',message)
        self.assertIn('status=500',message)
        self.assertIn('exception=ProviderError',message)
        self.assertIn('retry_after=7',message)
        self.assertIn('stage=normal_png',message)
        self.assertIn('stage=reduced_png',message)
        self.assertIn('stage=jpeg_fallback',message)
        self.assertNotIn('secret-api-key',message)
        self.assertNotIn('key-a',message)

if __name__=='__main__': unittest.main()

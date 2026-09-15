import hashlib
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

import pymupdf
from app import database, book_manager, package_service
from app.search_service import search_pages


class CollectionPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.patches = [patch.object(database, 'DB', self.root/'source.db'), patch.object(book_manager, 'BOOKS', self.root/'source-books')]
        for item in self.patches: item.start()
        database.init_db(); book_manager.BOOKS.mkdir()
        self.collection = str(uuid.uuid4())
        with database.connect() as db:
            self.collection_id = db.execute("INSERT INTO collections(uuid,title,created_at) VALUES(?,?,?)", (self.collection, 'Three volumes', '2026-01-01')).lastrowid
        self.books = [self.add_book(number) for number in range(1, 4)]

    def tearDown(self):
        for item in reversed(self.patches): item.stop()
        self.tmp.cleanup()

    def add_book(self, number):
        uid = str(uuid.uuid4()); pdf = book_manager.BOOKS/f'{uid}.pdf'
        with pymupdf.open() as document:
            document.new_page(); document.save(pdf)
        with database.connect() as db:
            book_id = db.execute("INSERT INTO books(book_uuid,title,original_filename,stored_filename,file_path,file_hash,page_count,status,created_at,updated_at,collection_id,volume_number) VALUES(?,?,?,?,?,?,1,'completed','','',?,?)", (uid, f'Volume {number}', f'{number}.pdf', pdf.name, str(pdf), hashlib.sha256(pdf.read_bytes()).hexdigest(), self.collection_id, number)).lastrowid
            page_id = db.execute("INSERT INTO book_pages(book_id,page_number,status,extracted_text,created_at,updated_at) VALUES(?,1,'completed',?,'','')", (book_id, f'collection text {number}')).lastrowid
            db.execute('INSERT INTO page_search VALUES(?,?,?)', (page_id, f'collection text {number}', f'collection text {number}'))
        return uid, pdf.read_bytes()

    def test_complete_collection_roundtrip_preserves_members_order_and_search(self):
        archive, _ = package_service.export_collection_package(self.collection)
        self.addCleanup(lambda: Path(archive).unlink(missing_ok=True))
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(set(bundle.namelist()), {'manifest.json','collection.json'} | {f'books/{uid}/{name}' for uid,_ in self.books for name in ('manifest.json','pages.json','original.pdf')})
            self.assertNotIn(b'secret', b''.join(bundle.read(name) for name in bundle.namelist() if not name.endswith('.pdf')))
        target = self.root/'target-books'
        with patch.object(database, 'DB', self.root/'target.db'), patch.object(book_manager, 'BOOKS', target):
            database.init_db()
            with open(archive, 'rb') as incoming:
                self.assertEqual(package_service.import_collection_package(incoming), self.collection)
            with database.connect() as db:
                collection = db.execute('SELECT * FROM collections WHERE uuid=?', (self.collection,)).fetchone()
                rows = db.execute('SELECT * FROM books WHERE collection_id=? ORDER BY volume_number', (collection['id'],)).fetchall()
            self.assertEqual([row['book_uuid'] for row in rows], [uid for uid,_ in self.books])
            self.assertEqual([Path(row['file_path']).read_bytes() for row in rows], [pdf for _,pdf in self.books])
            self.assertEqual(len(search_pages('collection', collection_id=collection['id'])), 3)

    def test_incomplete_volume_blocks_export(self):
        with database.connect() as db: db.execute("UPDATE book_pages SET status='failed' WHERE book_id=(SELECT id FROM books WHERE book_uuid=?)", (self.books[1][0],))
        with self.assertRaises(ValueError): package_service.export_collection_package(self.collection)

    def test_malformed_member_rolls_back_collection(self):
        archive, _ = package_service.export_collection_package(self.collection)
        self.addCleanup(lambda: Path(archive).unlink(missing_ok=True))
        bad = self.root/'bad.zip'
        with zipfile.ZipFile(archive) as source, zipfile.ZipFile(bad, 'w') as target:
            for info in source.infolist():
                if info.filename.endswith('original.pdf') and self.books[2][0] in info.filename: continue
                target.writestr(info, source.read(info.filename))
        target_books = self.root/'rollback-books'
        with patch.object(database, 'DB', self.root/'rollback.db'), patch.object(book_manager, 'BOOKS', target_books):
            database.init_db()
            with open(bad, 'rb') as incoming:
                with self.assertRaises(ValueError): package_service.import_collection_package(incoming)
            with database.connect() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM collections').fetchone()[0], 0)
            self.assertFalse(target_books.exists() and list(target_books.iterdir()))


if __name__ == '__main__': unittest.main()

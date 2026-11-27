import json, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import patch
from app import database, key_backup, secrets, gemini_key_manager as keys
from app.ocr_service import current_key_selection

class KeyBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'secrets.json'; self.patch=patch.object(secrets,'SECRETS_FILE',self.path); self.patch.start()
        self.enterContext(patch.object(database, 'DB', self.path.parent/'library.db'))
        database.init_db()
        self.ids=[str(uuid.uuid4()),str(uuid.uuid4())]
        with database.connect() as db:
            db.execute("UPDATE settings SET value='pool' WHERE key='ocr_key_mode'")
            db.execute("UPDATE settings SET value=? WHERE key='ocr_pool_ids'", (json.dumps(self.ids),))
        secrets.save_secrets({'gemini_api_keys':[{'id':self.ids[0],'name':'One','api_key':'fake-secret-alpha','enabled':True},{'id':self.ids[1],'name':'Two','api_key':'fake-secret-beta','enabled':False}], 'active_gemini_key_id':self.ids[0], 'ocr_key_mode':'single','ocr_pool_ids':[]})
    def tearDown(self): self.patch.stop(); self.tmp.cleanup()
    def test_encrypted_roundtrip_and_no_plaintext(self):
        blob=key_backup.export_backup('correct horse battery')
        self.assertNotIn(b'fake-secret-alpha',blob); self.assertEqual(key_backup.decrypt_backup(blob,'correct horse battery')['ocr_pool_ids'],self.ids)
        with self.assertRaises(ValueError): key_backup.decrypt_backup(blob,'wrong password here')
        with self.assertRaises(ValueError): key_backup.decrypt_backup(blob[:-1]+b'x','correct horse battery')
    def test_merge_and_replace_confirmation(self):
        blob=key_backup.export_backup('correct horse battery'); secrets.save_secrets({'gemini_api_keys':[]})
        key_backup.restore_backup(blob,'correct horse battery','merge'); self.assertEqual(len(secrets.load_secrets()['gemini_api_keys']),2)
        with self.assertRaises(ValueError): key_backup.restore_backup(blob,'correct horse battery','replace')
        key_backup.restore_backup(blob,'correct horse battery','replace',True); self.assertEqual(secrets.load_secrets()['active_gemini_key_id'],self.ids[0])

    def test_restore_replaces_effective_pool_and_merge_preserves_empty_pool(self):
        blob = key_backup.export_backup('correct horse battery')
        with database.connect() as db:
            db.execute("UPDATE settings SET value='[]' WHERE key='ocr_pool_ids'")
        key_backup.restore_backup(blob, 'correct horse battery', 'merge')
        self.assertEqual(current_key_selection(), ('pool', []))
        key_backup.restore_backup(blob, 'correct horse battery', 'replace', True)
        self.assertEqual(current_key_selection(), ('pool', self.ids))
        self.assertEqual(keys.acquire_key(*current_key_selection())['id'], self.ids[0])

    def test_recover_interrupted_credential_commit(self):
        import os
        replace = os.replace
        def interrupt(source, target):
            if Path(source).suffix == '.pending':
                raise OSError('interrupted after DB commit')
            replace(source, target)
        with patch.object(secrets.os, 'replace', side_effect=interrupt):
            with self.assertRaises(OSError):
                keys.delete_key(self.ids[0])
        self.assertEqual(current_key_selection(), ('pool', self.ids[1:]))
        self.assertEqual([k['id'] for k in keys.list_keys()], self.ids[1:])
        self.assertFalse(self.path.with_suffix('.pending').exists())

    def test_uncommitted_staged_keys_are_discarded(self):
        original = secrets.load_secrets()
        self.path.with_suffix('.pending').write_text(json.dumps({'generation':'uncommitted'}))
        self.assertEqual(secrets.load_secrets(), original)

if __name__=='__main__': unittest.main()

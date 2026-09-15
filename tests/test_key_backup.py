import json, tempfile, unittest, uuid
from pathlib import Path
from unittest.mock import patch
from app import key_backup, secrets

class KeyBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'secrets.json'; self.patch=patch.object(secrets,'SECRETS_FILE',self.path); self.patch.start()
        self.ids=[str(uuid.uuid4()),str(uuid.uuid4())]
        secrets.save_secrets({'gemini_api_keys':[{'id':self.ids[0],'name':'One','api_key':'fake-secret-alpha','enabled':True},{'id':self.ids[1],'name':'Two','api_key':'fake-secret-beta','enabled':False}], 'active_gemini_key_id':self.ids[0], 'ocr_key_mode':'pool','ocr_pool_ids':self.ids})
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

if __name__=='__main__': unittest.main()

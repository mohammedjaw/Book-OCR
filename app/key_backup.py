"""Password-encrypted, versioned Gemini key backup files."""
import base64, json, os, uuid
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from .gemini_key_manager import MAX_GEMINI_API_KEYS, _store
from .database import connect, read_key_selection
from .secrets import LOCK, commit_with_selection

MAGIC = 'Book-OCR-Key-Backup'; VERSION = 1
KDF = {'name':'scrypt','n':32768,'r':8,'p':1,'length':32}

def _derive(password, salt):
    return Scrypt(salt=salt, length=KDF['length'], n=KDF['n'], r=KDF['r'], p=KDF['p']).derive(password.encode('utf-8'))

def _payload(data, mode, pool):
    keys = data.get('gemini_api_keys', [])
    return {'keys':[{'id':k['id'],'name':k.get('name',''),'api_key':k['api_key'],'enabled':bool(k.get('enabled',True))} for k in keys],
            'active_key_id':data.get('active_gemini_key_id'),'ocr_key_mode':mode,'ocr_pool_ids':pool}

def export_backup(password):
    if len(password) < 12: raise ValueError('Use a password with at least 12 characters.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        with LOCK:
            data, keys = _store()
            mode, pool = read_key_selection(db)
            known = {key['id'] for key in keys}
            snapshot = _payload(data, mode, [key_id for key_id in pool if key_id in known])
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode()
    salt, nonce = os.urandom(16), os.urandom(12)
    header = {'magic':MAGIC,'version':VERSION,'algorithm':'AES-256-GCM','kdf':KDF,'salt':base64.b64encode(salt).decode(),'nonce':base64.b64encode(nonce).decode()}
    cipher = AESGCM(_derive(password, salt)).encrypt(nonce, payload, json.dumps(header,sort_keys=True,separators=(',',':')).encode())
    return json.dumps({**header,'ciphertext':base64.b64encode(cipher).decode()}, separators=(',',':')).encode()

def _valid(payload):
    if not isinstance(payload,dict) or set(payload) != {'keys','active_key_id','ocr_key_mode','ocr_pool_ids'}: raise ValueError
    keys=payload['keys']
    if not isinstance(keys,list) or len(keys)>MAX_GEMINI_API_KEYS: raise ValueError
    ids=[]; secrets=[]
    for item in keys:
        if not isinstance(item,dict) or set(item) != {'id','name','api_key','enabled'}: raise ValueError
        if str(uuid.UUID(item['id'])) != item['id'] or not isinstance(item['name'],str) or not item['name'].strip() or not isinstance(item['api_key'],str) or not item['api_key'].isascii() or not item['api_key'] or not isinstance(item['enabled'],bool): raise ValueError
        ids.append(item['id']); secrets.append(item['api_key'])
    if len(set(ids)) != len(ids) or len(set(secrets)) != len(secrets): raise ValueError
    if payload['active_key_id'] is not None and payload['active_key_id'] not in ids: raise ValueError
    if payload['ocr_key_mode'] not in ('single','pool') or not isinstance(payload['ocr_pool_ids'],list) or any(item not in ids for item in payload['ocr_pool_ids']): raise ValueError
    return payload

def decrypt_backup(blob, password):
    try:
        outer=json.loads(blob); header={key:outer[key] for key in ('magic','version','algorithm','kdf','salt','nonce')}
        if header['magic'] != MAGIC or header['version'] != VERSION or header['algorithm'] != 'AES-256-GCM' or header['kdf'] != KDF: raise ValueError
        raw=AESGCM(_derive(password,base64.b64decode(header['salt']))).decrypt(base64.b64decode(header['nonce']),base64.b64decode(outer['ciphertext']),json.dumps(header,sort_keys=True,separators=(',',':')).encode())
        return _valid(json.loads(raw))
    except Exception: raise ValueError('Backup could not be decrypted. Check the password and file.') from None

def restore_backup(blob, password, mode, confirmed=False):
    incoming=decrypt_backup(blob,password)
    if mode not in ('merge','replace') or (mode == 'replace' and not confirmed): raise ValueError('Replace requires explicit confirmation.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        with LOCK:
            current, existing = _store()
            if mode == 'replace' or not existing:
                final = incoming['keys']
                active = incoming['active_key_id']
                key_mode, pool = incoming['ocr_key_mode'], incoming['ocr_pool_ids']
            else:
                # Existing scheduler choices (including an empty pool) survive merge.
                key_mode, pool = read_key_selection(db)
                final = list(existing)
                ids = {item['id'] for item in final}
                by_secret = {item['api_key']: item['id'] for item in final}
                remap = {}
                for item in incoming['keys']:
                    if item['api_key'] not in by_secret:
                        new_id = str(uuid.uuid4()) if item['id'] in ids else item['id']
                        final.append({**item, 'id': new_id})
                        ids.add(new_id)
                        by_secret[item['api_key']] = new_id
                    remap[item['id']] = by_secret[item['api_key']]
                active = current.get('active_gemini_key_id') or remap.get(incoming['active_key_id'])
            if len(final) > MAX_GEMINI_API_KEYS:
                raise ValueError('Import would exceed the maximum of 10 Gemini keys.')
            enabled = [item['id'] for item in final if item['enabled']]
            if active not in enabled:
                active = next(iter(enabled), None)
            current.update(gemini_api_keys=final, active_gemini_key_id=active)
            for legacy in ('gemini_api_key', 'ocr_key_mode', 'ocr_pool_ids'):
                current.pop(legacy, None)
            db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)',
                           [('ocr_key_mode', key_mode), ('ocr_pool_ids', json.dumps(pool))])
            commit_with_selection(db, current)

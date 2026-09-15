"""Password-encrypted, versioned Gemini key backup files."""
import base64, json, os, uuid
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from .gemini_key_manager import MAX_GEMINI_API_KEYS
from .secrets import LOCK, load_secrets, save_secrets

MAGIC = 'Book-OCR-Key-Backup'; VERSION = 1
KDF = {'name':'scrypt','n':32768,'r':8,'p':1,'length':32}

def _derive(password, salt):
    return Scrypt(salt=salt, length=KDF['length'], n=KDF['n'], r=KDF['r'], p=KDF['p']).derive(password.encode('utf-8'))

def _payload(data):
    keys = data.get('gemini_api_keys', [])
    return {'keys':[{'id':k['id'],'name':k.get('name',''),'api_key':k['api_key'],'enabled':bool(k.get('enabled',True))} for k in keys],
            'active_key_id':data.get('active_gemini_key_id'),'ocr_key_mode':data.get('ocr_key_mode','single'),'ocr_pool_ids':data.get('ocr_pool_ids',[])}

def export_backup(password):
    if len(password) < 12: raise ValueError('Use a password with at least 12 characters.')
    with LOCK: payload = json.dumps(_payload(load_secrets()), ensure_ascii=False, separators=(',',':')).encode()
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
    with LOCK:
        current=load_secrets(); existing=current.get('gemini_api_keys',[])
        if mode == 'replace': final=[dict(item) for item in incoming['keys']]; active=incoming['active_key_id']; pool=incoming['ocr_pool_ids']; key_mode=incoming['ocr_key_mode']
        else:
            final=[dict(item) for item in existing]; known_secrets={item.get('api_key') for item in final}; known_ids={item.get('id') for item in final}; remap={}
            for item in incoming['keys']:
                if item['api_key'] in known_secrets: continue
                copy=dict(item)
                if copy['id'] in known_ids: copy['id']=str(uuid.uuid4())
                remap[item['id']]=copy['id']; final.append(copy); known_secrets.add(copy['api_key']); known_ids.add(copy['id'])
            if len(final)>MAX_GEMINI_API_KEYS: raise ValueError('Import would exceed the maximum of 10 Gemini keys.')
            active=current.get('active_gemini_key_id') or remap.get(incoming['active_key_id'])
            pool=current.get('ocr_pool_ids',[]) or [remap[item] for item in incoming['ocr_pool_ids'] if item in remap]
            key_mode=current.get('ocr_key_mode','single')
        if len(final)>MAX_GEMINI_API_KEYS: raise ValueError('Import would exceed the maximum of 10 Gemini keys.')
        current['gemini_api_keys']=final; current.pop('gemini_api_key',None); current['active_gemini_key_id']=active; current['ocr_key_mode']=key_mode; current['ocr_pool_ids']=pool
        save_secrets(current)

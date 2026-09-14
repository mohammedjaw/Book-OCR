from datetime import datetime
from zoneinfo import ZoneInfo
import time
import uuid
from .secrets import load_secrets, save_secrets, LOCK

MAX_GEMINI_API_KEYS = 10
REQUEST_INTERVAL = 2.0
_next_request = 0.0

def _day():
    return datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()

def _store():
    data = load_secrets()
    keys = data.setdefault('gemini_api_keys', [])
    changed = False
    if data.get('gemini_api_key') and not keys:
        keys.append({'id': str(uuid.uuid4()), 'name': 'Gemini Key 1', 'api_key': data['gemini_api_key'], 'enabled': True})
        data['active_gemini_key_id'] = keys[0]['id']; changed = True
    for key in keys:
        if key.get('quota_day') != _day():
            key.update(quota_day=_day(), requests=0, successes=0, failures=0, cooldown_until=0)
            if key.get('last_status') != 'invalid_key': key['last_status'] = 'available'
            changed = True
    if changed: save_secrets(data)
    return data, keys

def list_keys():
    with LOCK:
        data, keys = _store()
        return [{'id': k['id'], 'name': k['name'], 'masked_key': '••••' + k['api_key'][-4:],
                 'is_active': k['id'] == data.get('active_gemini_key_id'),
                 'requests': k.get('requests', 0), 'successes': k.get('successes', 0),
                 'failures': k.get('failures', 0), 'last_status': k.get('last_status', 'available')} for k in keys]

def get_active_key():
    with LOCK:
        data, keys = _store()
        return next((dict(k) for k in keys if k['id'] == data.get('active_gemini_key_id') and k.get('enabled', True)), None)

def set_active_key(key_id):
    with LOCK:
        data, keys = _store()
        if not any(k['id'] == key_id and k.get('enabled', True) for k in keys): return False
        data['active_gemini_key_id'] = key_id; save_secrets(data); return True

def add_key(name, secret):
    if not secret or not secret.isascii(): return False
    with LOCK:
        data, keys = _store()
        if len(keys) >= MAX_GEMINI_API_KEYS or any(k['api_key'] == secret for k in keys): return False
        item = {'id': str(uuid.uuid4()), 'name': name.strip() or f'Gemini Key {len(keys)+1}', 'api_key': secret, 'enabled': True}
        keys.append(item); data.setdefault('active_gemini_key_id', item['id']); save_secrets(data)
        return True

class KeysUnavailable(Exception):
    pass

class SchedulingPaused(Exception):
    pass

def acquire_key(mode, pool_ids, stop=None):
    global _next_request
    while True:
        if stop and stop.is_set(): raise SchedulingPaused()
        with LOCK:
            data, keys = _store()
            selected = pool_ids if mode == 'pool' else [data.get('active_gemini_key_id')]
            usable = [k for k in keys if k['id'] in selected and k.get('enabled', True) and k.get('last_status') not in ('quota_exhausted', 'invalid_key')]
            if not usable: raise KeysUnavailable('No usable selected Gemini key remains. Check key settings or the next quota day.')
            key = min(usable, key=lambda k: (k.get('cooldown_until', 0), k.get('last_scheduled', 0)))
            now = time.time(); delay = max(_next_request, key.get('cooldown_until', 0)) - now
            if delay <= 0:
                _next_request = now + REQUEST_INTERVAL
                key['last_scheduled'] = now
                save_secrets(data)
                return dict(key)
        if stop:
            if stop.wait(min(delay, 1)): raise SchedulingPaused()
        else: time.sleep(min(delay, 1))

def record_request(key_id, success=None, status=None, error='', cooldown=0, request_day=None):
    with LOCK:
        data, keys = _store()
        key = next((k for k in keys if k['id'] == key_id), None)
        if not key: return
        if request_day is not None and request_day != _day(): return
        if success is None:
            key['requests'] = key.get('requests', 0) + 1
        else:
            field = 'successes' if success else 'failures'
            key[field] = key.get(field, 0) + 1
        if key.get('last_status') not in ('quota_exhausted', 'invalid_key'):
            key['last_status'] = status or key.get('last_status', 'available')
        if cooldown: key['cooldown_until'] = max(key.get('cooldown_until', 0), time.time() + cooldown)
        key['last_used_at'] = datetime.now().isoformat()
        # Provider messages are intentionally not persisted: they may contain secrets.
        save_secrets(data)
        return _day()

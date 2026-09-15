import json
import os
from threading import RLock
from .paths import CONFIG_ROOT

SECRETS_FILE = CONFIG_ROOT / 'secrets.json'
LOCK = RLock()

def load_secrets():
    with LOCK:
        if not SECRETS_FILE.exists():
            return {}
        # Never silently replace a corrupt store with an empty one.
        return json.loads(SECRETS_FILE.read_text(encoding='utf-8'))

def save_secrets(values):
    with LOCK:
        SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = SECRETS_FILE.with_suffix('.tmp')
        with temporary.open('w', encoding='utf-8') as out:
            json.dump(values, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, SECRETS_FILE)

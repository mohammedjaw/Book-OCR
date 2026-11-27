import json
import os
import uuid
from threading import RLock
from .paths import CONFIG_ROOT

SECRETS_FILE = CONFIG_ROOT / 'secrets.json'
LOCK = RLock()

def load_secrets():
    with LOCK:
        pending = SECRETS_FILE.with_suffix('.pending')
        if pending.exists():
            # SQLite's transaction decides which key set survived an interruption.
            from .database import connect
            with connect() as db:
                generation = db.execute("SELECT value FROM settings WHERE key='key_store_generation'").fetchone()
            staged = json.loads(pending.read_text(encoding='utf-8'))
            if generation and staged['generation'] == generation[0]:
                os.replace(pending, SECRETS_FILE)
            else:
                pending.unlink()
        if not SECRETS_FILE.exists():
            return {}
        # Never silently replace a corrupt store with an empty one.
        return json.loads(SECRETS_FILE.read_text(encoding='utf-8'))

def _write(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as out:
        json.dump(values, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, path)

def save_secrets(values):
    with LOCK:
        _write(SECRETS_FILE, values)

def commit_with_selection(db, values):
    """Caller holds a SQLite write transaction and LOCK, in that order."""
    generation = uuid.uuid4().hex
    pending = SECRETS_FILE.with_suffix('.pending')
    _write(pending, {**values, 'generation': generation})
    db.execute("INSERT OR REPLACE INTO settings VALUES ('key_store_generation', ?)", (generation,))
    db.commit()
    os.replace(pending, SECRETS_FILE)

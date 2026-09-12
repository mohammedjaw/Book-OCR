import json
from pathlib import Path

SECRETS_FILE = Path(__file__).parent.parent / "config" / "secrets.json"

def load_secrets():
    if not SECRETS_FILE.exists():
        return {}
    try:
        return json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

def save_secrets(values):
    SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRETS_FILE.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")

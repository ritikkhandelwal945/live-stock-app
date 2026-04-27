import json
import os
from datetime import date
from pathlib import Path

# Project-local default: `<repo>/data/.kite_token.json`. Same `data/` directory
# already used by holdings_store, news_provider, fundamentals cache, etc.
# Living next to the project means switching terminals (or rebuilding the venv)
# doesn't lose the token — only Zerodha's mandatory 6 AM IST expiry does.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TOKEN_FILE = _PROJECT_ROOT / "data" / ".kite_token.json"

# Legacy location used by older builds. We read this as a fallback so users
# who already authenticated under the old layout don't have to log in again.
_LEGACY_TOKEN_FILE = Path.home() / ".config" / "live-stock-app" / "token.json"


def _resolved_token_file() -> Path:
    override = os.environ.get("KITE_TOKEN_FILE")
    return Path(override).expanduser() if override else _DEFAULT_TOKEN_FILE


# Backwards-compatible module-level constants (some callers/tests import these).
TOKEN_FILE = _resolved_token_file()
CONFIG_DIR = TOKEN_FILE.parent


def save_token(access_token: str) -> None:
    path = _resolved_token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "access_token": access_token,
        "date": date.today().isoformat(),
    }))


def _read_valid_token(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if data.get("date") != date.today().isoformat():
        return None
    return data.get("access_token")


def load_token() -> str | None:
    primary = _resolved_token_file()
    token = _read_valid_token(primary)
    if token:
        return token

    # Legacy fallback: migrate forward so subsequent reads hit the new path.
    legacy_token = _read_valid_token(_LEGACY_TOKEN_FILE)
    if legacy_token:
        try:
            save_token(legacy_token)
        except OSError:
            pass
        return legacy_token

    return None


def clear_token() -> None:
    for path in (_resolved_token_file(), _LEGACY_TOKEN_FILE):
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass

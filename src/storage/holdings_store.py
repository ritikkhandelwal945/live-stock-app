import json
from datetime import datetime, timezone
from pathlib import Path

from src.client.models import Holding

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
STORE_PATH = DATA_DIR / "holdings.json"


def save_holdings(holdings: list[Holding]) -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "holdings": [h.model_dump() for h in holdings],
    }
    STORE_PATH.write_text(json.dumps(payload, indent=2))
    return payload["uploaded_at"]


def load_holdings() -> tuple[list[Holding], str | None]:
    if not STORE_PATH.exists():
        return [], None
    payload = json.loads(STORE_PATH.read_text())
    holdings = [Holding(**h) for h in payload.get("holdings", [])]
    return holdings, payload.get("uploaded_at")


def clear_holdings() -> None:
    if STORE_PATH.exists():
        STORE_PATH.unlink()

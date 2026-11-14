"""Per-user saved products, medications and recall alerts, kept as JSON files in .data/.

The original app wrote to a Firebase Realtime Database whose service-account
key is not in the repository, so it could not run for anyone but its author.
Local files need no credentials and are enough for a single-machine demo.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from datetime import datetime, timezone
from pathlib import Path

from .models import Product, Recall

DATA_DIR = Path(__file__).resolve().parent.parent / ".data"
_EMPTY = {"items": [], "meds": [], "alerts": [], "state": "", "last_check": ""}


def _path(uid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", uid or "guest")
    return DATA_DIR / f"{safe}.json"


def load(uid: str = "guest") -> dict:
    try:
        data = json.loads(_path(uid).read_text())
    except (OSError, ValueError):
        data = {}
    return {**_EMPTY, **data}


def save(uid: str, data: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = _path(uid).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(_path(uid))  # Atomic, so the scheduler and the app cannot corrupt each other.


def users() -> list[str]:
    return sorted(p.stem for p in DATA_DIR.glob("*.json")) if DATA_DIR.exists() else []


def _product(d: dict) -> Product:
    known = {f.name for f in fields(Product)}
    return Product(**{k: v for k, v in d.items() if k in known})


def items(uid: str = "guest") -> list[Product]:
    return [_product(d) for d in load(uid)["items"]]


def add_item(uid: str, product: Product) -> bool:
    """Save a product to the watchlist. Returns False if it was already there."""
    data = load(uid)
    key = product.barcode or product.title
    if any((d.get("barcode") or _product(d).title) == key for d in data["items"]):
        return False
    data["items"].append(asdict(product))
    save(uid, data)
    return True


def remove_item(uid: str, key: str) -> None:
    data = load(uid)
    data["items"] = [d for d in data["items"] if (d.get("barcode") or _product(d).title) != key]
    save(uid, data)


def meds(uid: str = "guest") -> list[str]:
    return list(load(uid)["meds"])


def set_meds(uid: str, names: list[str]) -> None:
    data = load(uid)
    seen: list[str] = []
    for name in names:
        name = name.strip().lower()
        if name and name not in seen:
            seen.append(name)
    data["meds"] = seen
    save(uid, data)


def state(uid: str = "guest") -> str:
    return load(uid)["state"]


def set_state(uid: str, code: str) -> None:
    data = load(uid)
    data["state"] = code
    save(uid, data)


def alerts(uid: str = "guest") -> list[dict]:
    return list(load(uid)["alerts"])


def add_alerts(uid: str, recalls: list[Recall]) -> list[Recall]:
    """Record recalls found by the scheduler. Returns only the ones not seen before."""
    data = load(uid)
    seen = {(a["source"], a["recall_id"]) for a in data["alerts"]}
    new = [r for r in recalls if (r.source, r.recall_id) not in seen]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["alerts"] = [{**asdict(r), "found_at": now} for r in new] + data["alerts"]
    save(uid, data)
    return new


def mark_checked(uid: str = "guest") -> None:
    data = load(uid)
    data["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(uid, data)


def last_check(uid: str = "guest") -> str:
    return load(uid)["last_check"]

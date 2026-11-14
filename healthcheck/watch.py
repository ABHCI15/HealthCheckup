"""Scheduled re-check of every saved item and medication.

Run once for all users:

    venv/bin/python -m healthcheck.watch

Loop forever, checking every 60 minutes:

    venv/bin/python -m healthcheck.watch --every 60

Cron example (every morning at 07:00):

    0 7 * * * cd "/path/to/HealthCheckup" && venv/bin/python -m healthcheck.watch >> .cache/watch.log 2>&1
"""

from __future__ import annotations

import argparse
import time

from . import barcode, products, recalls
from .models import Recall

try:
    from . import store
except Exception:  # pragma: no cover - store.py is written by another module owner
    store = None


def run_once(uid: str = "guest") -> list[Recall]:
    """Re-check one user's items and medications. Returns only recalls not alerted before."""
    if store is None:
        return []
    found: list[Recall] = []
    try:
        items = list(store.items(uid))
    except Exception:
        items = []
    try:
        meds = list(store.meds(uid))
    except Exception:
        meds = []
    for product in items:
        try:
            code = barcode.parse(product.barcode) if product.barcode else None
            report = recalls.check(product, code)
        except Exception:
            continue
        found += [r for r in report.recalls if r.confirmed or (r.source == "FDA drug" and r.match == "name")]
    for med in meds:
        try:
            report = recalls.check(products.from_name(med, "drug"))
        except Exception:
            continue
        found += [r for r in report.recalls if r.confirmed or (r.source == "FDA drug" and r.match == "name")]
    unique: dict[tuple[str, str], Recall] = {}
    for r in found:
        unique.setdefault((r.source, r.recall_id), r)
    try:
        new = list(store.add_alerts(uid, list(unique.values())))
    except Exception:
        new = []
    try:
        store.mark_checked(uid)
    except Exception:
        pass
    return new


def run_all() -> dict[str, list[Recall]]:
    if store is None:
        print("healthcheck.store is not available; nothing to check")
        return {}
    try:
        uids = list(store.users()) or ["guest"]
    except Exception:
        uids = ["guest"]
    out: dict[str, list[Recall]] = {}
    for uid in uids:
        new = run_once(uid)
        out[uid] = new
        print(f"{time.strftime('%Y-%m-%d %H:%M')} {uid}: {len(new)} new alert(s)")
        for r in new:
            print(f"  [{r.source} {r.recall_id}] {r.match}: {r.title[:90]}")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Re-check saved items and medications for recalls")
    parser.add_argument("--every", type=float, metavar="MINUTES", help="repeat forever at this interval")
    args = parser.parse_args(argv)
    run_all()
    while args.every:
        time.sleep(max(args.every, 0.1) * 60)
        run_all()


if __name__ == "__main__":
    main()

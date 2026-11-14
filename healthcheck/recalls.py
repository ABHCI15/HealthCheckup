"""Check a product against CPSC, FDA (openFDA enforcement) and USDA FSIS recalls.

Nothing here ever says a product is safe: every source reports a SourceStatus
so the UI can say "no recalls found in the sources that answered".
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import requests

from .barcode import Barcode, digits_in_text
from .models import Product, Recall, RecallReport, SourceStatus

HEADERS = {"User-Agent": "healthcheckup/0.1"}
TIMEOUT = 12
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CPSC_CACHE = CACHE_DIR / "cpsc.json"
CPSC_URL = "https://www.saferproducts.gov/RestWebServices/Recall?format=json&RecallDateStart=1970-01-01"
CPSC_PAGE = "https://www.cpsc.gov/Recalls"
FDA_PAGE = "https://www.accessdata.fda.gov/scripts/ires/"
FDA_ENDPOINTS = {
    "FDA food": "https://api.fda.gov/food/enforcement.json",
    "FDA drug": "https://api.fda.gov/drug/enforcement.json",
}
FSIS_URL = "https://www.fsis.usda.gov/fsis/api/recall/v/1"
FSIS_PAGE = "https://www.fsis.usda.gov/recalls"
FSIS_BLOCKED = "FSIS blocks automated access; check meat, poultry and egg recalls on its site"
_STOP = {"with", "from", "that", "this", "pack", "count", "size", "original", "brand", "ounce", "each"}
_RANK = {"barcode": 0, "lot": 1, "ndc": 2, "name": 3, "area": 4}


def _fetch(url: str, timeout: int = TIMEOUT):
    """One GET. Returns (status_code, parsed JSON or None). Tests replace this."""
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    try:
        data = r.json()
    except ValueError:
        data = None
    return r.status_code, data


def _iso(value: str) -> str:
    value = (value or "").strip()
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if re.match(r"\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return ""


def _days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _words(product: Product) -> list[str]:
    """Significant words (4+ letters) of the product name that are not part of the brand."""
    brand = set(re.findall(r"[a-z]+", product.brand.lower()))
    out: list[str] = []
    for w in re.findall(r"[a-z]{4,}", product.name.lower()):
        if w not in brand and w not in _STOP and w not in out:
            out.append(w)
    return out


def _has_phrase(phrase: str, text: str) -> bool:
    return bool(phrase) and re.search(r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)", text.lower()) is not None


def _short(reason) -> str:
    text = str(reason).strip() or reason.__class__.__name__
    return text[:120]


# --------------------------------------------------------------------------
# CPSC
# --------------------------------------------------------------------------

_CPSC_MEM: tuple[float, list, dict] | None = None


def _names(items) -> list[str]:
    return [i.get("Name") or "" for i in items or [] if isinstance(i, dict) and i.get("Name")]


def _cpsc_load() -> list[dict]:
    """The slim CPSC recall list, from .cache/cpsc.json when under 24 hours old. Raises on failure."""
    try:
        if time.time() - CPSC_CACHE.stat().st_mtime < 86400:
            return json.loads(CPSC_CACHE.read_text())
    except (OSError, ValueError):
        pass
    try:
        status, data = _fetch(CPSC_URL, 60)
        if status != 200 or not isinstance(data, list) or len(data) < 100:
            raise RuntimeError(f"CPSC returned HTTP {status} without a recall list")
    except Exception:
        try:  # A stale copy beats no answer.
            return json.loads(CPSC_CACHE.read_text())
        except (OSError, ValueError):
            pass
        raise
    slim = [
        {
            "RecallNumber": r.get("RecallNumber") or "",
            "RecallDate": r.get("RecallDate") or "",
            "Title": r.get("Title") or "",
            "URL": r.get("URL") or "",
            "Description": (r.get("Description") or "")[:400],
            "Products": _names(r.get("Products")),
            "Hazards": _names(r.get("Hazards")),
            "Remedies": _names(r.get("Remedies")),
            "Manufacturers": _names(r.get("Manufacturers")),
            "ProductUPCs": [u.get("UPC") or "" for u in r.get("ProductUPCs") or [] if isinstance(u, dict)],
        }
        for r in data if isinstance(r, dict)
    ]
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        CPSC_CACHE.write_text(json.dumps(slim))
    except OSError:
        pass
    return slim


def _cpsc_data() -> tuple[list, dict]:
    global _CPSC_MEM
    if _CPSC_MEM and time.time() - _CPSC_MEM[0] < 86400:
        return _CPSC_MEM[1], _CPSC_MEM[2]
    records = _cpsc_load()
    index: dict[str, list] = {}
    for r in records:
        for upc in r.get("ProductUPCs") or []:
            digits = re.sub(r"\D", "", upc)
            if digits:
                index.setdefault(digits, []).append(r)
    _CPSC_MEM = (time.time(), records, index)
    return records, index


def _cpsc_recall(r: dict, match: str, detail: str) -> Recall:
    return Recall(
        source="CPSC",
        recall_id=str(r.get("RecallNumber") or ""),
        title=r.get("Title") or "; ".join(r.get("Products") or []),
        date=_iso(r.get("RecallDate") or ""),
        reason="; ".join(r.get("Hazards") or []) or r.get("Description") or "",
        remedy="; ".join(r.get("Remedies") or []),
        url=r.get("URL") or CPSC_PAGE,
        firm="; ".join(r.get("Manufacturers") or []),
        match=match,
        match_detail=detail,
    )


def _cpsc(product: Product, code: Barcode | None) -> tuple[list[Recall], SourceStatus]:
    try:
        records, index = _cpsc_data()
    except Exception as e:
        return [], SourceStatus("CPSC", False, _short(e), CPSC_PAGE)
    out: list[Recall] = []
    seen: set[str] = set()
    for v in (code.variants() if code else []):
        for r in index.get(v, []):
            if r["RecallNumber"] not in seen:
                seen.add(r["RecallNumber"])
                out.append(_cpsc_recall(r, "barcode", f"Barcode {v} is listed in this recall"))
    words = _words(product)
    if product.brand and words:
        cutoff = _days_ago(5 * 365).strftime("%Y-%m-%d")
        named: list[Recall] = []
        for r in records:
            if r["RecallNumber"] in seen or _iso(r.get("RecallDate") or "") < cutoff:
                continue
            head = " ".join([r.get("Title") or ""] + (r.get("Products") or []) + (r.get("Manufacturers") or []))
            if not _has_phrase(product.brand, head):
                continue
            body = (head + " " + (r.get("Description") or "")).lower()
            hit = next((w for w in words if re.search(r"\b" + re.escape(w), body)), None)
            if hit:
                named.append(_cpsc_recall(r, "name", f'Same brand "{product.brand}" and the word "{hit}"; compare the model on your product'))
        named.sort(key=lambda x: x.date, reverse=True)
        out += named[:5]
    detail = f"{len(out)} possible match(es)" if out else f"No match in {len(records)} recalls"
    return out, SourceStatus("CPSC", True, detail, CPSC_PAGE)


# --------------------------------------------------------------------------
# FDA (openFDA enforcement reports)
# --------------------------------------------------------------------------

@lru_cache(maxsize=512)
def _openfda(url: str) -> tuple:
    """Results of one openFDA query. 404 means no matches. Raises on failure (failures are not cached)."""
    status, data = _fetch(url)
    if status == 404:
        return ()
    if status != 200 or not isinstance(data, dict):
        raise RuntimeError(f"openFDA returned HTTP {status}")
    return tuple(data.get("results") or [])


def _q(value: str) -> str:
    return "%22" + quote(value.replace('"', " ").strip(), safe="") + "%22"


def _fda_recall(source: str, r: dict, match: str, detail: str) -> Recall:
    desc = " ".join((r.get("product_description") or "").split())
    return Recall(
        source=source,
        recall_id=r.get("recall_number") or "",
        title=desc[:160],
        date=_iso(r.get("report_date") or "") or _iso(r.get("recall_initiation_date") or ""),
        reason=r.get("reason_for_recall") or "",
        remedy="",
        url=FDA_PAGE,
        firm=r.get("recalling_firm") or "",
        status=r.get("status") or "",
        classification=r.get("classification") or "",
        match=match,
        match_detail=detail,
    )


def _fda(source: str, product: Product, code: Barcode | None) -> tuple[list[Recall], SourceStatus]:
    base = FDA_ENDPOINTS[source]
    found: dict[str, Recall] = {}
    lot = (product.lot or (code.lot if code else "") or "").strip()

    def add(r: dict, match: str, detail: str) -> None:
        if lot and match not in ("barcode", "lot") and lot.lower() in (r.get("code_info") or "").lower():
            match, detail = "lot", f"Lot {lot} is listed in this recall"
        rec = _fda_recall(source, r, match, detail)
        old = found.get(rec.recall_id)
        if old is None or _RANK[match] < _RANK[old.match]:
            found[rec.recall_id] = rec

    try:
        variants = code.variants() if code and code.gtin else []
        for v in [v for v in variants if len(v) in (12, 13)]:
            for r in _openfda(f"{base}?search=(code_info:{_q(v)}+product_description:{_q(v)})&limit=20"):
                text = (r.get("product_description") or "") + " " + (r.get("code_info") or "")
                hit = digits_in_text(variants, text)
                if hit:
                    add(r, "barcode", f"Barcode {hit} is printed in this recall notice")
        if lot:
            for r in _openfda(f"{base}?search=code_info:{_q(lot)}&limit=20"):
                if lot.lower() in (r.get("code_info") or "").lower():
                    add(r, "lot", f"Lot {lot} is listed in this recall")
        since = f"report_date:[{_days_ago(730):%Y%m%d}+TO+{datetime.now(timezone.utc):%Y%m%d}]"
        if source == "FDA drug":
            if product.ndc:
                for r in _openfda(f"{base}?search=openfda.product_ndc:{_q(product.ndc)}&limit=20"):
                    add(r, "ndc", f"NDC {product.ndc} is named in this recall; check the lot on your package")
            generic = (product.generic_name or "").strip()
            if generic:
                url = f"{base}?search=openfda.generic_name:{_q(generic)}+AND+{since}&sort=report_date:desc&limit=10"
                for r in _openfda(url):
                    add(r, "name", f"Same drug from {r.get('recalling_firm') or 'another firm'}; check the lot on your package")
        else:
            words = _words(product)
            if product.brand and words:
                url = (f"{base}?search=product_description:{_q(product.brand)}+AND+product_description:{_q(words[0])}"
                       f"+AND+{since}&sort=report_date:desc&limit=5")
                for r in _openfda(url):
                    desc = r.get("product_description") or ""
                    if _has_phrase(product.brand, desc):
                        add(r, "name", f'Same brand "{product.brand}" and the word "{words[0]}"; compare the codes on your package')
    except Exception as e:
        return list(found.values()), SourceStatus(source, False, _short(e), FDA_PAGE)
    detail = f"{len(found)} possible match(es)" if found else "No matching recalls"
    return list(found.values()), SourceStatus(source, True, detail, FDA_PAGE)


# --------------------------------------------------------------------------
# USDA FSIS
# --------------------------------------------------------------------------

def _fsis(product: Product) -> tuple[list[Recall], SourceStatus]:
    try:
        status, data = _fetch(FSIS_URL)
    except Exception as e:
        return [], SourceStatus("USDA FSIS", False, _short(e), FSIS_PAGE)
    if status != 200 or not isinstance(data, list):
        return [], SourceStatus("USDA FSIS", False, FSIS_BLOCKED, FSIS_PAGE)
    out: list[Recall] = []
    words = _words(product)
    if product.brand and words:
        cutoff = _days_ago(730).strftime("%Y-%m-%d")
        for r in data:
            if not isinstance(r, dict):
                continue
            text = f"{r.get('field_title', '')} {r.get('field_product_items', '')} {r.get('field_summary', '')}"
            date = _iso(str(r.get("field_recall_date") or ""))
            if date < cutoff or not _has_phrase(product.brand, text):
                continue
            hit = next((w for w in words if w in text.lower()), None)
            if hit:
                out.append(Recall(
                    source="USDA FSIS", recall_id=str(r.get("field_recall_number") or ""),
                    title=str(r.get("field_title") or ""), date=date,
                    reason=str(r.get("field_recall_reason") or ""), url=str(r.get("field_recall_url") or FSIS_PAGE),
                    firm=str(r.get("field_establishment") or ""), classification=str(r.get("field_recall_classification") or ""),
                    match="name", match_detail=f'Same brand "{product.brand}" and the word "{hit}"',
                ))
    out.sort(key=lambda x: x.date, reverse=True)
    return out[:5], SourceStatus("USDA FSIS", True, f"{len(out[:5])} possible match(es)" if out else "No matching recalls", FSIS_PAGE)


# --------------------------------------------------------------------------

def check(product: Product, code: Barcode | None = None) -> RecallReport:
    """Check every source. Never raises; a source that fails is reported with ok=False."""
    report = RecallReport(checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    jobs = []
    if product.kind != "drug":
        jobs.append(lambda: _cpsc(product, code))
    if product.kind == "food":
        fda = ["FDA food"]
    elif product.kind == "drug":
        fda = ["FDA drug"]
    else:
        fda = ["FDA food", "FDA drug"]
    for source in fda:
        jobs.append(lambda s=source: _fda(s, product, code))
    if product.kind != "drug":
        jobs.append(lambda: _fsis(product))
    for job in jobs:
        try:
            recalls, status = job()
        except Exception as e:  # Belt and braces: no source may break the report.
            recalls, status = [], SourceStatus("Recall source", False, _short(e), "")
        report.recalls += recalls
        report.sources.append(status)
    report.recalls.sort(key=lambda r: r.date, reverse=True)
    report.recalls.sort(key=lambda r: not r.confirmed)
    return report

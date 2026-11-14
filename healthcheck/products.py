"""Turn a barcode (or a typed name) into a Product using openFDA and Open Food Facts."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote

import requests

from .barcode import Barcode
from .models import Product

HEADERS = {"User-Agent": "healthcheckup/0.1"}
TIMEOUT = 12
OFF_FIELDS = "product_name,brands,ingredients_text,allergens_tags,categories_tags,image_front_small_url"


@lru_cache(maxsize=512)
def _json(url: str):
    """GET JSON. Returns None for 404 (openFDA's 'no matches'). Raises on other failures (not cached)."""
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _safe(url: str):
    try:
        return _json(url)
    except Exception:
        return None


def _first(value) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _drug(code: Barcode) -> Product | None:
    upc = code.gtin[1:]
    data = _safe(f"https://api.fda.gov/drug/label.json?search=openfda.upc:%22{upc}%22&limit=1")
    results = (data or {}).get("results") or []
    if results:
        o = results[0].get("openfda") or {}
        brand = _first(o.get("brand_name"))
        return Product(
            kind="drug", name=brand, brand=brand,
            generic_name=_first(o.get("generic_name")),
            substances=list(o.get("substance_name") or []),
            ndc=_first(o.get("product_ndc")),
            manufacturer=_first(o.get("manufacturer_name")),
            ingredients=_first(results[0].get("active_ingredient"))[:600],
            source="openFDA drug label",
            source_url=f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?query={upc[1:]}",
        )
    for ndc in code.ndc_candidates():
        data = _safe(f"https://api.fda.gov/drug/ndc.json?search=packaging.package_ndc:%22{ndc}%22&limit=1")
        results = (data or {}).get("results") or []
        if results:
            r = results[0]
            brand = r.get("brand_name") or r.get("generic_name") or ""
            return Product(
                kind="drug", name=brand, brand=brand,
                generic_name=r.get("generic_name") or "",
                substances=[a.get("name", "") for a in r.get("active_ingredients") or [] if a.get("name")],
                ndc=r.get("product_ndc") or "",
                manufacturer=r.get("labeler_name") or "",
                source="openFDA NDC directory",
                source_url=f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?query={quote(ndc)}",
            )
    return None


def _strip(tags) -> list[str]:
    return [t.split(":", 1)[1] if ":" in t else t for t in tags or []]


def _food(code: Barcode) -> Product | None:
    tried: list[str] = []
    for bc in (code.upc, code.gtin[1:]):
        if not bc or bc in tried:
            continue
        tried.append(bc)
        data = _safe(f"https://world.openfoodfacts.org/api/v2/product/{quote(bc)}.json?fields={OFF_FIELDS}")
        if not data or data.get("status") != 1:
            continue
        p = data.get("product") or {}
        return Product(
            kind="food",
            name=(p.get("product_name") or "").strip(),
            brand=(p.get("brands") or "").split(",")[0].strip(),
            image_url=p.get("image_front_small_url") or "",
            ingredients=p.get("ingredients_text") or "",
            allergens=_strip(p.get("allergens_tags")),
            categories=_strip(p.get("categories_tags")),
            source="Open Food Facts",
            source_url=f"https://world.openfoodfacts.org/product/{bc}",
        )
    return None


def identify(code: Barcode) -> Product:
    """Look a barcode up. Never raises; an unidentified code comes back with kind="unknown"."""
    product = None
    try:
        if code.gtin:
            if code.gtin.startswith("003"):
                product = _drug(code)
            if product is None:
                product = _food(code)
    except Exception:
        product = None
    if product is None:
        product = Product(kind="unknown")
    product.barcode = code.display
    product.lot = code.lot
    product.expiry = code.expiry
    return product


def from_name(name: str, kind: str = "unknown") -> Product:
    """Manual entry. For drugs the name is treated as the generic name."""
    name = (name or "").strip()
    product = Product(kind=kind, name=name, source="typed by user")
    if kind == "drug":
        product.generic_name = name
    return product

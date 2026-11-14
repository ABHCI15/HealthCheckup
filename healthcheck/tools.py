"""Tools shared by the Claude agent (healthcheck/ai.py) and the MCP server (mcp_server.py).

Every function returns a JSON-serialisable dict and never raises: a failure comes
back as {"error": "..."} so the model (or MCP client) can say a source did not answer
instead of treating silence as "safe". The docstrings are the tool descriptions Claude reads.
"""

from __future__ import annotations

import json
from typing import Any, Callable

MAX_CHARS = 6000  # rough ceiling for one tool result
_STR_LIMIT = 500


def _trim(value: Any, max_items: int) -> Any:
    if isinstance(value, dict):
        return {k: _trim(v, max_items) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        items = [_trim(v, max_items) for v in value[:max_items]]
        if len(value) > max_items:
            items.append(f"... {len(value) - max_items} more not shown")
        return items
    if isinstance(value, str) and len(value) > _STR_LIMIT:
        return value[:_STR_LIMIT] + "..."
    return value


def _compact(data: dict) -> dict:
    """Shorten long lists and strings until the result fits in about MAX_CHARS."""
    out = data
    for max_items in (12, 8, 5, 3, 2, 1):
        out = _trim(data, max_items)
        if len(json.dumps(out, default=str)) <= MAX_CHARS:
            return out
    out["truncated"] = True
    return out


def _dump(obj: Any) -> dict:
    from healthcheck import models

    return models.to_dict(obj)


def _error(exc: BaseException) -> dict:
    return {"error": f"{type(exc).__name__}: {exc}"[:400]}


def lookup_barcode(barcode: str) -> dict:
    """Identify a retail product from its barcode and check it for recalls.

    Use when the user gives a UPC, EAN or GTIN number (8 to 14 digits), or a drug NDC
    barcode. Returns {"product": {...}, "recalls": {...}}. "product" has kind
    ("food", "drug", "other", "unknown"), name, brand, ingredients, allergens and, for
    drugs, generic_name and substances, plus the source that identified it.
    "recalls" lists matching recalls from CPSC, FDA and USDA FSIS; each has "match":
    "barcode", "lot" or "ndc" means this exact product is recalled, "name" means only a
    similar name matched. "recalls.sources" says which sources answered: a source with
    ok=false was NOT checked, so never report "no recall" for it.
    """
    try:
        from healthcheck import barcode as barcode_mod
        from healthcheck import products, recalls

        code = barcode_mod.parse(str(barcode))
        if code is None or not (code.gtin or any(ch.isdigit() for ch in code.raw)):
            return {"error": f"'{barcode}' is not a valid barcode number"}
        product = products.identify(code)
        report = recalls.check(product, code)
        out = {"product": _dump(product), "recalls": _dump(report)}
        if not code.checksum_ok:
            out["barcode_warning"] = "check digit does not match; the number may be mistyped"
        elif code.note:
            out["barcode_warning"] = code.note
        return _compact(out)
    except Exception as exc:  # never raise into the agent loop
        return _error(exc)


def check_recalls(name: str, kind: str = "unknown", brand: str = "") -> dict:
    """Check a product for recalls by name when there is no barcode.

    name: the product or generic drug name, e.g. "peanut butter" or "metformin".
    kind: "food", "drug", "other" or "unknown". brand: optional brand to narrow matches.
    Returns {"product": {...}, "recalls": {...}} in the same shape as lookup_barcode.
    All matches here are name matches (possible, not confirmed for the user's own item):
    tell the user to compare lot numbers and dates on the package with the recall notice.
    Check "recalls.sources" for sources that failed to answer.
    """
    try:
        from healthcheck import products, recalls

        product = products.from_name(name, kind)
        if brand:
            product.brand = brand
        report = recalls.check(product)
        return _compact({"product": _dump(product), "recalls": _dump(report)})
    except Exception as exc:
        return _error(exc)


def drug_targets(drug: str) -> dict:
    """Get the proteins a medicine acts on and is processed by, with evidence.

    drug: generic or brand name, e.g. "warfarin" or "Zocor".
    Returns a drug profile: normalised generic name, "links" (each a protein gene
    symbol such as CYP3A4 or VKORC1 with relation "target", "metabolised by",
    "transported by", "inhibits" or "induces", and the evidence source), and
    "food_evidence" (sentences from the drug's FDA label that mention food, drink or
    meals), plus any boxed warning and the label URL. An empty "name" means the drug
    was not found. Use this to explain how a drug works at the protein level.
    """
    try:
        from healthcheck import drugs

        return _compact(_dump(drugs.profile(drug)))
    except Exception as exc:
        return _error(exc)


def food_drug_interactions(food: str, drugs: list[str]) -> dict:
    """Find protein-level interactions between a food and the user's medicines.

    food: a food name or a full ingredient list as printed, e.g. "grapefruit juice".
    drugs: generic or brand names of the medicines the user takes, e.g. ["simvastatin"].
    Returns "interactions", each one path food -> protein <- drug: the food, its active
    component, "via" (the protein gene symbol, or "absorption"), what the food does to
    that protein, how the drug relates to it, the plain-language consequence, the advice
    ("avoid", "separate by hours", "keep intake consistent", "monitor"), whether the
    drug's own FDA label confirms it, and evidence with sources. An empty list means no
    interaction was found in the sources checked, not that the combination is safe.
    """
    try:
        from healthcheck import interactions

        if isinstance(drugs, str):
            drugs = [d.strip() for d in drugs.split(",") if d.strip()]
        report = _dump(interactions.analyze(food, list(drugs)))
        # The path list is the point; full drug profiles are available via drug_targets.
        for profile in report.get("drugs", []):
            if isinstance(profile, dict):
                profile.pop("links", None)
                profile.pop("food_evidence", None)
        return _compact(report)
    except Exception as exc:
        return _error(exc)


def local_health_briefing(state: str) -> dict:
    """Get recent recalls and public-health signals for a US state.

    state: two-letter US state code, e.g. "CA".
    Returns recalls distributed in that state in roughly the last 30 days and health
    signals (such as influenza or COVID-19 levels with trend and date), plus "sources"
    showing which upstream feeds answered. Use for "what should I know about in my area".
    """
    try:
        from healthcheck import local

        return _compact(_dump(local.briefing(str(state).strip().upper())))
    except Exception as exc:
        return _error(exc)


TOOLS: dict[str, Callable[..., dict]] = {
    "lookup_barcode": lookup_barcode,
    "check_recalls": check_recalls,
    "drug_targets": drug_targets,
    "food_drug_interactions": food_drug_interactions,
    "local_health_briefing": local_health_briefing,
}

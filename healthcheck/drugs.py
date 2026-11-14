"""Drug profile: RxNorm id, Open Targets mechanism targets, and FDA label text (openFDA).

Every protein link comes from an Open Targets response or from a quoted label sentence.
"""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import quote

import requests

from .models import DrugProfile, DrugProteinLink, Evidence, Protein, SourceStatus

TIMEOUT = 12
HEADERS = {"User-Agent": "healthcheckup/0.1"}
RXNORM_URL = "https://rxnav.nlm.nih.gov/REST/rxcui.json"
OT_URL = "https://api.platform.opentargets.org/api/v4/graphql"
FDA_URL = "https://api.fda.gov/drug/label.json"

FOOD_SECTIONS = [
    "drug_interactions", "information_for_patients", "dosage_and_administration", "boxed_warning",
    "warnings_and_cautions", "warnings", "do_not_use", "ask_doctor", "ask_doctor_or_pharmacist",
    "when_using", "spl_medguide", "clinical_pharmacology", "pharmacokinetics",
]
ENZYME_SECTIONS = ["drug_interactions", "clinical_pharmacology", "pharmacokinetics"]

_SPECIFIC = (
    r"grapefruit|alcohol(?:ic)?|milk|dairy|calcium|iron|antacids?|vitamin\s+K|caffeine|coffee|tyramine|cheeses?|"
    r"potassium|licorice|liquorice|cranberry|green\s+tea|St\.?\s+John['’]?s\s+wort|high-fat|empty\s+stomach|fasting"
)
_SPECIFIC_RE = re.compile(rf"(?<![A-Za-z])(?:{_SPECIFIC})(?![A-Za-z])", re.I)
_FOOD_RE = re.compile(rf"(?<![A-Za-z])(?:{_SPECIFIC}|foods?|meals?|diet|dietary)(?![A-Za-z])", re.I)

_CYP_RE = re.compile(r"\bCYP\s?(\d[A-Z]\d+)\b")
_TRANSPORTERS = [
    (re.compile(r"\bP-?\s?glycoprotein\b|\bP-?gp\b", re.I), "ABCB1"),
    (re.compile(r"\bOATP\s?1B1\b"), "SLCO1B1"),
    (re.compile(r"\bOATP\s?1B3\b"), "SLCO1B3"),
    (re.compile(r"\bBCRP\b"), "ABCG2"),
    (re.compile(r"\bUGT\s?1A1\b"), "UGT1A1"),
]
_TRANSPORTER_SYMBOLS = {"ABCB1", "SLCO1B1", "SLCO1B3", "ABCG2"}
_NEGATION_RE = re.compile(
    r"\b(not|no|nor|neither|without|unlikely|negligible|minimal|minor|lack|lacks|little|weak|weakly)\b|n['’]t\b", re.I
)
_OTHER_SUBSTRATES_RE = re.compile(
    r"\bsubstrates\b|\b(drugs|agents|products|medicines|medications|compounds)\b[^.]{0,60}\bmetaboli[sz]ed\b", re.I
)
_SUBSTRATE_RE = re.compile(
    r"\bsubstrate\b|\bmetaboli[sz]ed\s+(?:\w+\s+){0,3}(?:by|via|through)\b|\bmetabolism\b[^.]*\b(?:by|via|through|mediated)\b"
    r"|\btransported\s+by\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+(?=[A-Z(\[0-9])", text) if s.strip()]


def _trim(text: str, n: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _get_json(url: str, **kw):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, **kw)
    return r.status_code, (r.json() if r.content else {})


# ---------------------------------------------------------------- RxNorm
def _rxnorm(name: str) -> tuple[str, SourceStatus]:
    url = f"{RXNORM_URL}?name={quote(name)}&search=2"
    try:
        code, data = _get_json(url)
        if code != 200:
            return "", SourceStatus("RxNorm", False, f"HTTP {code}", url)
        ids = (data.get("idGroup") or {}).get("rxnormId") or []
        if ids:
            return str(ids[0]), SourceStatus("RxNorm", True, f"rxcui {ids[0]}", url)
        return "", SourceStatus("RxNorm", True, "no match", url)
    except Exception as e:  # noqa: BLE001
        return "", SourceStatus("RxNorm", False, f"{type(e).__name__}: {e}"[:200], url)


# ---------------------------------------------------------------- Open Targets
_OT_SEARCH = '{ search(queryString: %s, entityNames: ["drug"]) { hits { id name entity } } }'
_OT_DRUG = """{ drug(chemblId: %s) { id name description drugType synonyms { label } tradeNames { label }
  mechanismsOfAction { rows { mechanismOfAction actionType targetName targets { id approvedSymbol approvedName } } } } }"""


def _gql(query: str) -> dict:
    r = requests.post(OT_URL, json={"query": query}, headers=HEADERS, timeout=TIMEOUT)
    data = r.json()
    if data.get("errors"):
        raise RuntimeError(str(data["errors"])[:200])
    return data.get("data") or {}


def _open_targets(name: str) -> tuple[dict, SourceStatus]:
    """Returns {"chembl_id", "name", "description", "links"} or {} when there is no confident match."""
    import json

    try:
        hits = (_gql(_OT_SEARCH % json.dumps(name)).get("search") or {}).get("hits") or []
        hits = [h for h in hits if h.get("entity") == "drug" and h.get("id")]
        q = name.strip().lower()
        for hit in hits[:3]:
            drug = _gql(_OT_DRUG % json.dumps(hit["id"])).get("drug") or {}
            names = {(drug.get("name") or "").lower()}
            for fld in ("synonyms", "tradeNames"):
                for s in drug.get(fld) or []:
                    lab = s.get("label") if isinstance(s, dict) else s
                    if lab:
                        names.add(str(lab).lower())
            if q not in names:
                continue  # fuzzy search hit that is not this drug: do not guess
            chembl = drug.get("id") or hit["id"]
            page = f"https://platform.opentargets.org/drug/{chembl}"
            links: list[DrugProteinLink] = []
            seen = set()
            for row in ((drug.get("mechanismsOfAction") or {}).get("rows") or []):
                for t in row.get("targets") or []:
                    sym = t.get("approvedSymbol") or ""
                    action = row.get("actionType") or ""
                    if not sym or (sym, action) in seen:
                        continue
                    seen.add((sym, action))
                    links.append(DrugProteinLink(
                        protein=Protein(symbol=sym, name=t.get("approvedName") or "", ensembl_id=t.get("id") or ""),
                        relation="target",
                        action=action,
                        evidence=[Evidence(text=row.get("mechanismOfAction") or "", source="Open Targets", url=page)],
                    ))
            out = {"chembl_id": chembl, "name": (drug.get("name") or "").lower(),
                   "description": drug.get("description") or "", "links": links}
            return out, SourceStatus("Open Targets", True, f"{chembl}, {len(links)} target link(s)", page)
        return {}, SourceStatus("Open Targets", True, "no match", OT_URL)
    except Exception as e:  # noqa: BLE001
        return {}, SourceStatus("Open Targets", False, f"{type(e).__name__}: {e}"[:200], OT_URL)


# ---------------------------------------------------------------- openFDA label
def _fda_label(name: str) -> tuple[dict, SourceStatus]:
    """Returns the label result dict ({} when none)."""
    term = quote(f'"{name}"')
    urls = [
        f"{FDA_URL}?search=openfda.generic_name:{term}+AND+_exists_:drug_interactions&limit=10",
        f"{FDA_URL}?search=openfda.generic_name:{term}&limit=10",
        f"{FDA_URL}?search=openfda.brand_name:{term}&limit=10",
    ]
    url = urls[0]
    try:
        for url in urls:
            code, data = _get_json(url)
            if code == 404:
                continue
            if code != 200:
                return {}, SourceStatus("openFDA label", False, f"HTTP {code}", url)
            results = data.get("results") or []
            if not results:
                continue
            q = name.strip().lower()

            def exact(res):
                g = [x.lower() for x in ((res.get("openfda") or {}).get("generic_name") or [])]
                return q in g

            def oral(res):
                return any("ORAL" in x.upper() for x in ((res.get("openfda") or {}).get("route") or []))

            # prefer the oral product (food matters there), then an exact generic-name match
            best = max(results, key=lambda r: (oral(r), exact(r)))
            return best, SourceStatus("openFDA label", True, "label found", url)
        return {}, SourceStatus("openFDA label", True, "no match", url)
    except Exception as e:  # noqa: BLE001
        return {}, SourceStatus("openFDA label", False, f"{type(e).__name__}: {e}"[:200], url)


def _section_text(label: dict, section: str) -> str:
    v = label.get(section)
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return str(v) if v else ""


def food_sentences(label: dict, label_url: str, limit: int = 12) -> list[Evidence]:
    specific, generic, seen = [], [], set()
    for section in FOOD_SECTIONS:
        for s in _sentences(_section_text(label, section)):
            if len(s) < 15 or not _FOOD_RE.search(s):
                continue
            key = re.sub(r"\W+", "", s.lower())[:120]
            if key in seen:
                continue
            seen.add(key)
            ev = Evidence(text=_trim(s), source=f"FDA label: {section}", url=label_url)
            (specific if _SPECIFIC_RE.search(s) else generic).append(ev)
    return (specific + generic)[:limit]


def _proteins_in(sentence: str) -> list[str]:
    out = []
    for m in _CYP_RE.finditer(sentence):
        sym = "CYP" + m.group(1)
        if sym not in out:
            out.append(sym)
    for rx, sym in _TRANSPORTERS:
        if rx.search(sentence) and sym not in out:
            out.append(sym)
    return out


def classify_sentence(sentence: str, drug_name: str) -> str:
    """'' | 'substrate' | 'inhibits' | 'induces' for the labelled drug, judged from the wording only."""
    if _NEGATION_RE.search(sentence):
        return ""  # "is not an inhibitor of ...": too easy to misread, skip
    s = sentence.lower()
    d = re.escape(drug_name.lower()) if drug_name else None
    if d:
        self_inh = re.search(rf"\b{d}\b[^.;]{{0,80}}\b(is|are|as)\s+(also\s+)?an?\s+[^.;]{{0,60}}\binhibitor\b", s) or \
            re.search(rf"\b{d}\b[^.;,]{{0,40}}\binhibits\b", s) or \
            re.search(rf"\binhibit(?:ion|ed)\b[^.;]{{0,60}}\bby\s+{d}\b", s)
        if self_inh:
            return "inhibits"
        self_ind = re.search(rf"\b{d}\b[^.;]{{0,80}}\b(is|are|as)\s+(also\s+)?an?\s+[^.;]{{0,60}}\binducer\b", s) or \
            re.search(rf"\b{d}\b[^.;,]{{0,40}}\binduces\b", s) or \
            re.search(rf"\binduc(?:tion|ed)\b[^.;]{{0,60}}\bby\s+{d}\b", s)
        if self_ind:
            return "induces"
    if _OTHER_SUBSTRATES_RE.search(sentence):
        return ""  # about other drugs that are substrates: says nothing safe about this one
    if re.search(r"\b(inhibitors?|inducers?)\b", s):
        return "substrate"  # "strong CYP3A4 inhibitors increase exposure": the drug is a substrate
    if _SUBSTRATE_RE.search(sentence):
        return "substrate"
    return ""


def label_links(label: dict, drug_name: str, label_url: str) -> list[DrugProteinLink]:
    links: dict[tuple[str, str], DrugProteinLink] = {}
    for section in ENZYME_SECTIONS:
        for s in _sentences(_section_text(label, section)):
            if len(s) > 700:
                continue
            proteins = _proteins_in(s)
            if not proteins:
                continue
            kind = classify_sentence(s, drug_name)
            if not kind:
                continue
            for sym in proteins:
                if kind == "substrate":
                    relation = "transported by" if sym in _TRANSPORTER_SYMBOLS else "metabolised by"
                else:
                    relation = kind
                if (sym, relation) in links:
                    continue
                links[(sym, relation)] = DrugProteinLink(
                    protein=Protein(symbol=sym), relation=relation,
                    evidence=[Evidence(text=_trim(s), source=f"FDA label: {section}", url=label_url)],
                )
    return list(links.values())


# ---------------------------------------------------------------- public
@lru_cache(maxsize=256)
def profile(name: str) -> DrugProfile:
    query = name
    q = (name or "").strip()
    p = DrugProfile(query=query)
    if not q:
        return p
    try:
        p.rxcui, st = _rxnorm(q)
        p.sources.append(st)

        ot, st = _open_targets(q)
        p.sources.append(st)
        if ot:
            p.chembl_id, p.description = ot["chembl_id"], ot["description"]
            p.links.extend(ot["links"])

        generic = ot.get("name") or q.lower()
        label, st = _fda_label(generic)
        if not label and generic != q.lower():
            label, st = _fda_label(q.lower())
        p.sources.append(st)
        if label:
            openfda = label.get("openfda") or {}
            if not ot:
                gn = (openfda.get("generic_name") or [q])[0].lower()
                generic = q.lower() if q.lower() in gn else gn
            set_id = label.get("set_id") or ""
            p.label_url = f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={set_id}" if set_id else ""
            p.boxed_warning = re.sub(r"\s+", " ", _section_text(label, "boxed_warning")).strip()[:400]
            p.food_evidence = food_sentences(label, p.label_url)
            p.links.extend(label_links(label, generic, p.label_url))
        if ot or label:
            p.name = generic
    except Exception as e:  # noqa: BLE001
        p.sources.append(SourceStatus("drug profile", False, f"{type(e).__name__}: {e}"[:200], ""))
    return p

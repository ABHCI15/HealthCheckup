"""The "near you" panel: recent recalls distributed in a state plus current public-health signals.

Sources (all keyless):
- openFDA food / drug enforcement reports, filtered by distribution pattern.
- CDC "Level of Acute Respiratory Illness (ARI) Activity by State" (data.cdc.gov f3zz-zga5): published level.
- CDC NSSP emergency department visits for COVID-19, flu, RSV by state (data.cdc.gov vutn-jzwm): weekly percent.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from urllib.parse import quote

import requests

from .models import LocalBriefing, Recall, Signal, SourceStatus

TIMEOUT = 12
HEADERS = {"User-Agent": "healthcheckup/0.1"}
MAX_PER_CATEGORY = 12
STALE_DAYS = 35  # a feed whose newest week is older than this is reported as stale, not shown

FDA_HUMAN_URL = "https://www.accessdata.fda.gov/scripts/ires/"
ARI_API = "https://data.cdc.gov/resource/f3zz-zga5.json"
ARI_HUMAN_URL = "https://www.cdc.gov/respiratory-viruses/data/activity-levels.html"
ED_API = "https://data.cdc.gov/resource/vutn-jzwm.json"
ED_HUMAN_URL = "https://www.cdc.gov/respiratory-viruses/data/index.html"
OUTBREAK_URL = "https://www.cdc.gov/foodborne-outbreaks/active-investigations/"

STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _get(url: str) -> requests.Response:
    return requests.get(url, headers=HEADERS, timeout=TIMEOUT)


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:120]


def _trim(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _iso(yyyymmdd: str) -> str:
    s = (yyyymmdd or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else s


# ---------------------------------------------------------------- recalls


def _fda_recalls(kind: str, code: str, name: str, days: int) -> tuple[list[Recall], SourceStatus]:
    source = f"FDA {kind}"
    end = date.today()
    start = end - timedelta(days=days)
    # Built by hand: openFDA needs the literal + signs and brackets.
    url = (
        f"https://api.fda.gov/{kind}/enforcement.json"
        f"?search=report_date:[{start:%Y%m%d}+TO+{end:%Y%m%d}]"
        f'+AND+(distribution_pattern:"{name.replace(" ", "+")}"'
        f'+distribution_pattern:"{code}"+distribution_pattern:nationwide)'
        f"&sort=report_date:desc&limit=50"
    )
    try:
        resp = _get(url)
        if resp.status_code == 404:  # openFDA's way of saying "no matches"
            return [], SourceStatus(source, True, f"No recalls reported in the last {days} days", FDA_HUMAN_URL)
        if resp.status_code != 200:
            return [], SourceStatus(source, False, f"HTTP {resp.status_code}", FDA_HUMAN_URL)
        data = resp.json()
        rows = data.get("results") or []
        total = (data.get("meta") or {}).get("results", {}).get("total", len(rows))
    except Exception as exc:  # network, JSON, anything: never raise to the caller
        return [], SourceStatus(source, False, _short(exc), FDA_HUMAN_URL)

    recalls = [
        Recall(
            source=source,
            recall_id=r.get("recall_number", ""),
            title=_trim(r.get("product_description", ""), 140),
            date=_iso(r.get("report_date", "")),
            reason=" ".join((r.get("reason_for_recall") or "").split()),
            url=FDA_HUMAN_URL,
            firm=r.get("recalling_firm", ""),
            status=r.get("status", ""),
            classification=r.get("classification", ""),
            match="area",
            match_detail=_trim(r.get("distribution_pattern", ""), 120),
        )
        for r in rows
        if isinstance(r, dict)
    ]
    recalls.sort(key=lambda r: r.date, reverse=True)  # newest first
    recalls.sort(key=lambda r: r.classification != "Class I")  # stable: Class I on top
    shown = recalls[:MAX_PER_CATEGORY]
    detail = f"{total} recalls in the last {days} days, showing {len(shown)}"
    return shown, SourceStatus(source, True, detail, FDA_HUMAN_URL)


# ---------------------------------------------------------------- signals


def _soda(base: str, name: str, limit: int) -> list[dict]:
    where = quote(f"geography='{name}'")
    resp = _get(f"{base}?$where={where}&$order={quote('week_end DESC')}&$limit={limit}")
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list):
        raise ValueError("unexpected response")
    return rows


def _is_stale(day: str) -> bool:
    try:
        return (date.today() - date.fromisoformat(day)).days > STALE_DAYS
    except ValueError:
        return True


def _ari_signal(name: str) -> tuple[list[Signal], SourceStatus]:
    source = "CDC respiratory activity"
    try:
        rows = _soda(ARI_API, name, 2)
    except Exception as exc:
        return [], SourceStatus(source, False, _short(exc), ARI_HUMAN_URL)
    if not rows:
        return [], SourceStatus(source, False, f"No data for {name}", ARI_HUMAN_URL)
    week = (rows[0].get("week_end") or "")[:10]
    label = (rows[0].get("label") or "").strip()
    if _is_stale(week):
        return [], SourceStatus(source, False, f"Stale: latest week ends {week or 'unknown'}", ARI_HUMAN_URL)
    # Level is CDC's published label. The contract has no "very low", so CDC "Very Low" and
    # "Minimal" are shown as "low" with the exact CDC wording kept in the detail text.
    level = {"very low": "low", "minimal": "low", "low": "low", "moderate": "moderate",
             "high": "high", "very high": "very high"}.get(label.lower(), "unknown")
    order = ["very low", "low", "moderate", "high", "very high"]
    trend = ""
    if len(rows) > 1:  # the feed currently publishes only the latest week, so this is usually empty
        a, b = label.lower(), (rows[1].get("label") or "").strip().lower()
        if a in order and b in order:
            d = order.index(a) - order.index(b)
            trend = "rising" if d > 0 else "falling" if d < 0 else "steady"
    sig = Signal(
        name="Respiratory illness (all causes)",
        level=level,
        trend=trend,
        detail=f'CDC rates acute respiratory illness activity in {name} as "{label or "not reported"}" '
               f"(share of emergency visits for respiratory illness).",
        as_of=week,
        url=ARI_HUMAN_URL,
    )
    return [sig], SourceStatus(source, True, f"Week ending {week}", ARI_HUMAN_URL)


def _ed_signals(name: str) -> tuple[list[Signal], SourceStatus]:
    source = "CDC emergency visits (COVID-19, flu, RSV)"
    try:
        rows = _soda(ED_API, name, 12)
    except Exception as exc:
        return [], SourceStatus(source, False, _short(exc), ED_HUMAN_URL)
    by_pathogen: dict[str, list[tuple[str, float]]] = {}
    for r in rows:  # newest first
        try:
            by_pathogen.setdefault(r["pathogen"], []).append((r["week_end"][:10], float(r["percent_visits"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not by_pathogen:
        return [], SourceStatus(source, False, f"No data for {name}", ED_HUMAN_URL)
    newest = max(v[0][0] for v in by_pathogen.values())
    if _is_stale(newest):
        return [], SourceStatus(source, False, f"Stale: latest week ends {newest}", ED_HUMAN_URL)
    signals = []
    for pathogen in sorted(by_pathogen):
        series = by_pathogen[pathogen]
        week, pct = series[0]
        if week != newest:
            continue
        trend, detail = "", f"{pct:g}% of emergency department visits in {name}"
        if len(series) > 1:
            prev = series[1][1]
            # Rule: the feed is published to 0.1 point, so any change of 0.1 or more is a move.
            diff = round(pct - prev, 2)
            trend = "rising" if diff >= 0.1 else "falling" if diff <= -0.1 else "steady"
            detail += f" (previous week {prev:g}%)"
        # CDC publishes no per-pathogen activity level here, so none is invented.
        signals.append(Signal(name=pathogen, level="unknown", trend=trend, detail=detail + ".",
                              as_of=week, url=ED_HUMAN_URL))
    return signals, SourceStatus(source, True, f"Week ending {newest}", ED_HUMAN_URL)


# ---------------------------------------------------------------- public API


@lru_cache(maxsize=128)
def _briefing(code: str, days: int) -> LocalBriefing:
    out = LocalBriefing(state=code)
    name = STATES.get(code)
    if not name:
        out.sources.append(SourceStatus("Location", False, f"Unknown state code: {code[:10]}", ""))
        return out
    for step in (lambda: _fda_recalls("food", code, name, days), lambda: _fda_recalls("drug", code, name, days)):
        items, status = step()
        out.recalls.extend(items)
        out.sources.append(status)
    for step in (lambda: _ari_signal(name), lambda: _ed_signals(name)):
        items, status = step()
        out.signals.extend(items)
        out.sources.append(status)
    out.sources.append(SourceStatus(
        "CDC foodborne outbreaks", True,
        "Not checked automatically; see CDC's list of active multistate investigations", OUTBREAK_URL))
    return out


def briefing(state: str, days: int = 30) -> LocalBriefing:
    """Recalls distributed in the state and current public-health signals. Never raises."""
    try:
        return _briefing(str(state or "").strip().upper(), int(days))
    except Exception as exc:
        return LocalBriefing(state=str(state), sources=[SourceStatus("Local briefing", False, _short(exc), "")])


briefing.cache_clear = _briefing.cache_clear  # type: ignore[attr-defined]

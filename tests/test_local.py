"""Offline tests for healthcheck.local: all HTTP is monkeypatched."""

from datetime import date, timedelta

import pytest

from healthcheck import local


class FakeResp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


RECENT = (date.today() - timedelta(days=6)).isoformat()
PREV = (date.today() - timedelta(days=13)).isoformat()


def fda_row(num, day, cls):
    return {"recall_number": num, "report_date": day, "classification": cls, "status": "Ongoing",
            "recalling_firm": "Firm", "product_description": "x" * 300, "reason_for_recall": "Listeria",
            "distribution_pattern": "CA, NV"}


def make_get(food=None, drug=None, ari=None, ed=None):
    def fake_get(url):
        for key, value in (("food/enforcement", food), ("drug/enforcement", drug),
                           ("f3zz-zga5", ari), ("vutn-jzwm", ed)):
            if key in url:
                if isinstance(value, Exception):
                    raise value
                return value if value is not None else FakeResp(404, {"error": {"code": "NOT_FOUND"}})
        raise AssertionError(url)
    return fake_get


@pytest.fixture(autouse=True)
def clear_cache():
    local.briefing.cache_clear()
    yield
    local.briefing.cache_clear()


def status(b, source):
    return next(s for s in b.sources if s.source == source)


def test_states():
    assert len(local.STATES) == 51 and local.STATES["DC"] == "District of Columbia"


def test_404_means_empty_not_failure(monkeypatch):
    monkeypatch.setattr(local, "_get", make_get(ari=FakeResp(200, []), ed=FakeResp(200, [])))
    b = local.briefing("CA")
    assert b.recalls == []
    assert status(b, "FDA food").ok and status(b, "FDA drug").ok


def test_class_one_first_then_newest(monkeypatch):
    rows = [fda_row("F-1", "20261110", "Class II"), fda_row("F-2", "20261101", "Class I"),
            fda_row("F-3", "20261105", "Class I"), fda_row("F-4", "20261112", "Class III")]
    monkeypatch.setattr(local, "_get", make_get(food=FakeResp(200, {"meta": {"results": {"total": 4}}, "results": rows})))
    b = local.briefing("ca")
    assert [r.recall_id for r in b.recalls] == ["F-3", "F-2", "F-4", "F-1"]
    first = b.recalls[0]
    assert first.source == "FDA food" and first.match == "area" and first.date == "2026-11-05"
    assert len(first.title) <= 140 and first.match_detail == "CA, NV"


def test_failure_yields_not_ok_and_no_signals(monkeypatch):
    boom = ConnectionError("down")
    monkeypatch.setattr(local, "_get", make_get(food=boom, drug=FakeResp(500, {}), ari=boom, ed=boom))
    b = local.briefing("CA")
    assert b.recalls == [] and b.signals == []
    for name in ("FDA food", "FDA drug", "CDC respiratory activity", "CDC emergency visits (COVID-19, flu, RSV)"):
        assert status(b, name).ok is False and status(b, name).detail
    assert any("foodborne-outbreaks" in s.url for s in b.sources)


def test_signals_level_and_trend(monkeypatch):
    ari = [{"week_end": RECENT + "T00:00:00.000", "geography": "California", "label": "Moderate"}]
    ed = [{"week_end": RECENT + "T00:00:00.000", "pathogen": "Influenza", "percent_visits": "3.0"},
          {"week_end": PREV + "T00:00:00.000", "pathogen": "Influenza", "percent_visits": "2.6"}]
    monkeypatch.setattr(local, "_get", make_get(ari=FakeResp(200, ari), ed=FakeResp(200, ed)))
    b = local.briefing("CA")
    assert [(s.name, s.level, s.trend, s.as_of) for s in b.signals] == [
        ("Respiratory illness (all causes)", "moderate", "", RECENT),
        ("Influenza", "unknown", "rising", RECENT),
    ]


def test_stale_feed_is_reported_not_shown(monkeypatch):
    ari = [{"week_end": "2024-10-05T00:00:00.000", "geography": "California", "label": "High"}]
    monkeypatch.setattr(local, "_get", make_get(ari=FakeResp(200, ari), ed=FakeResp(200, [])))
    b = local.briefing("CA")
    assert b.signals == []
    s = status(b, "CDC respiratory activity")
    assert not s.ok and "Stale" in s.detail


def test_unknown_state_does_not_raise(monkeypatch):
    monkeypatch.setattr(local, "_get", make_get())
    b = local.briefing("ZZ")
    assert b.recalls == [] and b.sources[0].ok is False

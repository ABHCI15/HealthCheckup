"""Offline tests for recall matching. All HTTP is replaced."""

from datetime import date

import pytest

from healthcheck import barcode, recalls
from healthcheck.models import Product

TODAY = date.today().isoformat()
CPSC = [
    {"RecallNumber": "24-001", "RecallDate": TODAY + "T00:00:00", "Title": "Hampton Bay Recalls Ceiling Fans",
     "URL": "https://cpsc.example/24-001", "Description": "Blades can detach.", "Products": ["Mara ceiling fans"],
     "Hazards": ["Injury hazard"], "Remedies": ["Replace"], "Manufacturers": ["King of Fans"],
     "ProductUPCs": ["8400 5961 4922"]},
    {"RecallNumber": "10-002", "RecallDate": "2010-01-01T00:00:00", "Title": "Hampton Bay Recalls Ceiling Fans (old)",
     "URL": "", "Description": "", "Products": [], "Hazards": [], "Remedies": [], "Manufacturers": [], "ProductUPCs": []},
]


def fda_row(**kw):
    row = {"recall_number": "H-1", "report_date": TODAY.replace("-", ""), "classification": "Class I",
           "status": "Ongoing", "recalling_firm": "Acme", "product_description": "Acme Vanilla Syrup UPC 8 10123 98065 9",
           "code_info": "Lot A1", "reason_for_recall": "Undeclared milk"}
    row.update(kw)
    return row


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    recalls._openfda.cache_clear()
    monkeypatch.setattr(recalls, "_CPSC_MEM", None)
    monkeypatch.setattr(recalls, "_cpsc_load", lambda: CPSC)
    monkeypatch.setattr(recalls, "_fetch", lambda url, timeout=12: (404, {"error": {}}))
    yield
    recalls._openfda.cache_clear()


def status(report, source):
    return next(s for s in report.sources if s.source == source)


def test_cpsc_barcode_match_and_404_means_empty():
    code = barcode.parse("840059614922")
    report = recalls.check(Product(barcode=code.display), code)
    assert [(r.recall_id, r.match) for r in report.recalls] == [("24-001", "barcode")]
    assert report.recalls[0].date == TODAY and report.recalls[0].confirmed
    assert status(report, "FDA food").ok and status(report, "FDA drug").ok
    fsis = status(report, "USDA FSIS")
    assert not fsis.ok and fsis.url == "https://www.fsis.usda.gov/recalls"


def test_cpsc_name_match_needs_brand_plus_word():
    def ids(p):
        return [r.recall_id for r in recalls._cpsc(p, None)[0]]
    assert ids(Product(brand="Hampton Bay", name="Mara Ceiling Fan 52 in")) == ["24-001"]  # old recall dropped
    assert ids(Product(brand="Hampton Bay", name="Patio Umbrella")) == []
    assert ids(Product(brand="", name="Ceiling Fan")) == []
    assert ids(Product(brand="Hampton", name="Hampton")) == []


def test_fda_barcode_is_confirmed_in_text(monkeypatch):
    code = barcode.parse("810123980659")
    rows = [fda_row(), fda_row(recall_number="H-2", product_description="Other 810123980650 thing")]
    monkeypatch.setattr(recalls, "_fetch", lambda url, timeout=12: (200, {"results": rows}) if "code_info" in url else (404, None))
    found, st = recalls._fda("FDA food", Product(kind="food"), code)
    assert st.ok and [(r.recall_id, r.match, r.date) for r in found] == [("H-1", "barcode", TODAY)]


def test_fda_lot_ndc_and_generic(monkeypatch):
    def fetch(url, timeout=12):
        if "product_ndc" in url:
            return 200, {"results": [fda_row(recall_number="D-1", code_info="Lot XY99, exp 01/27")]}
        if "generic_name" in url:
            return 200, {"results": [fda_row(recall_number="D-2", recalling_firm="Zed Pharma")]}
        return 404, None
    monkeypatch.setattr(recalls, "_fetch", fetch)
    p = Product(kind="drug", generic_name="metformin", ndc="1234-5678", lot="XY99")
    report = recalls.check(p)
    got = {r.recall_id: r for r in report.recalls}
    assert got["D-1"].match == "lot" and got["D-2"].match == "name"
    assert "Zed Pharma" in got["D-2"].match_detail
    assert report.recalls[0].recall_id == "D-1"  # confirmed first
    assert [s.source for s in report.sources] == ["FDA drug"]


def test_failures_give_ok_false(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("network down")
    monkeypatch.setattr(recalls, "_fetch", boom)
    monkeypatch.setattr(recalls, "_cpsc_load", boom)
    code = barcode.parse("810123980659")
    report = recalls.check(Product(kind="unknown", brand="Acme", name="Vanilla Syrup"), code)
    assert report.recalls == [] and report.checked_at
    assert len(report.sources) == 4 and all(not s.ok and s.detail and s.url for s in report.sources)

    monkeypatch.setattr(recalls, "_fetch", lambda url, timeout=12: (500, None))
    assert not recalls._fda("FDA food", Product(kind="food"), code)[1].ok

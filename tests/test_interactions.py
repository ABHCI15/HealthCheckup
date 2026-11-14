import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from healthcheck import drugs, foodmap, interactions  # noqa: E402
from healthcheck.models import DrugProfile, DrugProteinLink, Evidence, Protein  # noqa: E402


def keys(text):
    return {f.key for f in foodmap.find(text)}


def test_find_basic():
    assert "grapefruit" in keys("Grapefruit Juice")
    assert "vitamin_k" in keys("water, spinach, kale, salt")
    assert keys("") == set()


def test_cheese_is_dairy_not_tyramine():
    k = keys("cheese")
    assert "dairy_calcium" in k and "tyramine" not in k
    k = keys("aged cheddar cheese")
    assert "tyramine" in k and "dairy_calcium" in k


def test_whole_word_only():
    assert "caffeine" not in keys("steak")  # "tea" inside steak
    assert "iron" not in keys("environment")
    assert "alcohol" not in keys("brumous")
    assert "caffeine" in keys("green tea extract")


def _patch(monkeypatch, *profiles):
    table = {p.query: p for p in profiles}
    monkeypatch.setattr(drugs, "profile", lambda n: table.get(n, DrugProfile(query=n)))


def _link(sym, relation, action="", text="quoted"):
    return DrugProteinLink(Protein(sym), relation, action, [Evidence(text, "test")])


def test_inhibit_plus_metabolised(monkeypatch):
    _patch(monkeypatch, DrugProfile("simvastatin", name="simvastatin", links=[
        _link("HMGCR", "target", "INHIBITOR"), _link("CYP3A4", "metabolised by")]))
    r = interactions.analyze("grapefruit juice", ["simvastatin", " "])
    assert len(r.drugs) == 1 and len(r.interactions) == 1
    it = r.interactions[0]
    assert it.via == "CYP3A4" and it.advice == "avoid" and not it.label_confirms
    assert "slows the breakdown of simvastatin" in it.consequence
    assert any(e.source == "Food mechanism" for e in it.evidence)
    assert any(e.text == "quoted" for e in it.evidence)


def test_vitamin_k_target(monkeypatch):
    _patch(monkeypatch, DrugProfile("warfarin", name="warfarin", links=[_link("VKORC1", "target", "INHIBITOR")],
                                    food_evidence=[Evidence("Eat a normal diet; vitamin K can lower the effect.", "FDA label: x")]))
    r = interactions.analyze("spinach, kale", ["warfarin"])
    assert len(r.interactions) == 1
    it = r.interactions[0]
    assert it.via == "VKORC1" and it.advice == "keep intake consistent" and it.label_confirms
    assert "working against" in it.consequence


def test_tyramine_and_merge(monkeypatch):
    _patch(monkeypatch, DrugProfile("phenelzine", name="phenelzine", links=[
        _link("MAOA", "target", "INHIBITOR"), _link("MAOB", "target", "INHIBITOR")]))
    r = interactions.analyze("aged cheddar cheese", ["phenelzine"])
    assert {i.via for i in r.interactions} == {"MAOA", "MAOB"}  # dairy not emitted: no label confirmation
    assert all(i.advice == "avoid" and "tyramine" in i.consequence for i in r.interactions)


def test_absorption_only_with_label(monkeypatch):
    sent = "Do not take with milk or calcium-fortified juices alone since absorption may be reduced."
    _patch(monkeypatch,
           DrugProfile("cipro", name="ciprofloxacin", food_evidence=[Evidence(sent, "FDA label: x")]),
           DrugProfile("maoi", name="maoi", food_evidence=[Evidence("Foods to avoid: cheese, yogurt, beer.", "FDA label: x")]),
           DrugProfile("amlodipine", name="amlodipine",
                       food_evidence=[Evidence("Amlodipine is a calcium channel blocker; take with or without food.", "FDA label: x")]))
    r = interactions.analyze("milk", ["cipro", "amlodipine", "maoi", "nothing"])
    assert len(r.drugs) == 4 and not r.drugs[3].found
    assert len(r.interactions) == 1
    it = r.interactions[0]
    assert it.drug == "ciprofloxacin" and it.via == "absorption" and it.label_confirms
    assert it.advice == "separate by hours" and it.consequence == sent and it.drug_relation == "label warning"


def test_label_only_non_absorption(monkeypatch):
    _patch(monkeypatch, DrugProfile("x", name="x", food_evidence=[Evidence("Avoid grapefruit juice.", "FDA label: x")]))
    r = interactions.analyze("grapefruit", ["x"])
    assert [(i.via, i.advice, i.label_confirms) for i in r.interactions] == [("label", "monitor", True)]


def test_classify_sentence():
    c = drugs.classify_sentence
    assert c("Strong CYP3A4 inhibitors increase simvastatin exposure.", "simvastatin") == "substrate"
    assert c("Simvastatin is a substrate of CYP3A4.", "simvastatin") == "substrate"
    assert c("Ciprofloxacin is an inhibitor of CYP1A2.", "ciprofloxacin") == "inhibits"
    assert c("Simvastatin is not an inhibitor of CYP3A4.", "simvastatin") == ""
    assert c("Use with drugs metabolized by CYP1A2 raises their levels.", "ciprofloxacin") == ""

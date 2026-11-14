"""Join food factors to drugs through shared proteins, and through the drug's own label text."""

from __future__ import annotations

import re

from . import drugs, foodmap
from .models import DrugProfile, Evidence, FoodEffect, FoodFactor, Interaction, InteractionReport, SourceStatus

NON_PROTEIN = {"absorption", "potassium"}
# label phrases that contain a factor word but are not about the food
_NOT_FOOD_RE = re.compile(r"calcium[\s-]+channel|potassium[\s-]+(?:sparing|channel)|iron[\s-]+overload", re.I)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _rule(factor: FoodFactor, effect: FoodEffect, drug: str, relation: str, action: str) -> tuple[str, str, int]:
    """(consequence, advice, priority). Lower priority wins when several links share a protein."""
    food, fa, sym = factor.label, effect.action, effect.protein
    blocks = any(w in (action or "").upper() for w in ("INHIBITOR", "ANTAGONIST", "BLOCKER"))
    if fa == "inhibits" and relation in ("metabolised by", "transported by"):
        return f"{food} slows the breakdown of {drug}, so more of it stays in your body", "avoid", 0
    if fa == "induces" and relation in ("metabolised by", "transported by"):
        return f"{food} speeds up the breakdown of {drug}, so it may work less well", "monitor", 0
    if fa == "is the substrate of" and relation == "target" and blocks:
        if sym in ("MAOA", "MAOB"):
            return (f"{_cap(drug)} blocks the enzyme that clears tyramine, so tyramine can build up and raise "
                    f"blood pressure sharply"), "avoid", 0
        if sym == "VKORC1":
            return f"{food} supplies what {drug} is blocking, working against the medicine", "keep intake consistent", 0
    if fa == "is the substrate of" and relation == "inhibits":
        return (f"{_cap(drug)} slows the breakdown of {factor.component}, so its effects may be stronger and "
                f"last longer"), "monitor", 1
    return f"{food} and {drug} both act on {sym}, so one may change how the other works", "monitor", 2


# an absorption claim needs the label sentence itself to talk about absorption or dose timing
_ABSORPTION_RE = re.compile(r"absor|chelat|bioavailab|bind|hours?\s+(?:before|after)|separate|interfere", re.I)


def _label_hits(factor: FoodFactor, profile: DrugProfile) -> list[Evidence]:
    terms = list(factor.terms) + [factor.label, factor.component]
    physical = any(e.protein == "absorption" for e in factor.effects)
    out = []
    for ev in profile.food_evidence:
        text = _NOT_FOOD_RE.sub(" ", ev.text.replace("’", "'"))
        if physical and not _ABSORPTION_RE.search(text):
            continue
        if foodmap.mentions(text, terms):
            out.append(ev)
    return out


def _add_evidence(target: list[Evidence], new: list[Evidence]) -> None:
    for ev in new:
        if ev.text and not any(e.text == ev.text and e.source == ev.source for e in target):
            target.append(ev)


def analyze(food_text: str, drug_names: list[str]) -> InteractionReport:
    report = InteractionReport()
    report.factors = foodmap.find(food_text or "")
    seen_names = set()
    for n in drug_names or []:
        n = (n or "").strip()
        if not n or n.lower() in seen_names:
            continue
        seen_names.add(n.lower())
        try:
            report.drugs.append(drugs.profile(n))
        except Exception as e:  # noqa: BLE001
            report.drugs.append(DrugProfile(query=n, sources=[SourceStatus("drug profile", False, str(e)[:200])]))

    merged: dict[tuple[str, str, str], tuple[int, Interaction]] = {}
    for prof in report.drugs:
        if not prof.found:
            continue
        for factor in report.factors:
            label_ev = _label_hits(factor, prof)
            matched = False
            for effect in factor.effects:
                food_ev = [Evidence(text=effect.note, source="Food mechanism", url=effect.url)]
                if effect.protein in NON_PROTEIN:
                    continue
                for link in prof.links:
                    if link.protein.symbol != effect.protein:
                        continue
                    matched = True
                    consequence, advice, prio = _rule(factor, effect, prof.name, link.relation, link.action)
                    key = (prof.name, factor.label, effect.protein)
                    if key in merged and merged[key][0] <= prio:
                        _add_evidence(merged[key][1].evidence, link.evidence)
                        continue
                    it = Interaction(
                        drug=prof.name, food=factor.label, component=factor.component, via=effect.protein,
                        food_action=effect.action, drug_relation=link.relation, consequence=consequence,
                        advice=advice, label_confirms=bool(label_ev), evidence=[],
                    )
                    _add_evidence(it.evidence, link.evidence)
                    if key in merged:
                        _add_evidence(it.evidence, merged[key][1].evidence)
                    _add_evidence(it.evidence, label_ev[:2])
                    _add_evidence(it.evidence, food_ev)
                    merged[key] = (prio, it)
            if not matched and label_ev:
                effect = factor.effects[0]
                physical = effect.protein == "absorption"
                via = "absorption" if physical else "label"
                it = Interaction(
                    drug=prof.name, food=factor.label, component=factor.component, via=via,
                    food_action=effect.action if effect.protein in NON_PROTEIN else "mentioned on the label",
                    drug_relation="label warning", consequence=label_ev[0].text,
                    advice="separate by hours" if physical else "monitor", label_confirms=True, evidence=[],
                )
                _add_evidence(it.evidence, label_ev[:2])
                if effect.protein in NON_PROTEIN:
                    _add_evidence(it.evidence, [Evidence(text=effect.note, source="Food mechanism", url=effect.url)])
                merged[(prof.name, factor.label, via)] = (3, it)

    report.interactions = [it for _, it in merged.values()]

    seen = set()
    for prof in report.drugs:
        for st in prof.sources:
            if (st.source, st.ok) not in seen:
                seen.add((st.source, st.ok))
                report.sources.append(st)
    return report

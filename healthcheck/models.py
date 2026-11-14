"""Shared data types. Every module exchanges these, so treat this file as the contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class SourceStatus:
    """Whether one upstream data source answered. Shown to the user so a silent failure never reads as 'safe'."""

    source: str
    ok: bool
    detail: str = ""
    url: str = ""


@dataclass
class Product:
    barcode: str = ""
    kind: str = "unknown"  # "food" | "drug" | "other" | "unknown"
    name: str = ""
    brand: str = ""
    image_url: str = ""
    ingredients: str = ""  # free text as printed
    allergens: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    source: str = ""  # where the identification came from
    source_url: str = ""
    # Drugs only
    generic_name: str = ""
    substances: list[str] = field(default_factory=list)
    ndc: str = ""
    manufacturer: str = ""
    lot: str = ""
    expiry: str = ""

    @property
    def title(self) -> str:
        parts = [self.brand, self.name] if self.brand.lower() not in self.name.lower() else [self.name]
        return " ".join(p for p in parts if p) or self.generic_name or self.barcode or "Unknown product"


@dataclass
class Recall:
    source: str  # "CPSC" | "FDA food" | "FDA drug" | "FDA device" | "USDA FSIS"
    recall_id: str
    title: str
    date: str = ""  # ISO YYYY-MM-DD
    reason: str = ""
    remedy: str = ""
    url: str = ""
    firm: str = ""
    status: str = ""
    classification: str = ""  # FDA Class I / II / III when known
    match: str = "name"  # "barcode" | "lot" | "ndc" | "name" | "area"
    match_detail: str = ""

    @property
    def confirmed(self) -> bool:
        """True when the product's own code matched, as opposed to a similar name."""
        return self.match in ("barcode", "lot", "ndc")


@dataclass
class RecallReport:
    recalls: list[Recall] = field(default_factory=list)
    sources: list[SourceStatus] = field(default_factory=list)
    checked_at: str = ""

    @property
    def confirmed(self) -> list[Recall]:
        return [r for r in self.recalls if r.confirmed]

    @property
    def possible(self) -> list[Recall]:
        return [r for r in self.recalls if not r.confirmed]


@dataclass
class Evidence:
    text: str
    source: str  # e.g. "FDA label: drug_interactions"
    url: str = ""


@dataclass
class Protein:
    symbol: str  # HGNC gene symbol, e.g. "CYP3A4"
    name: str = ""
    ensembl_id: str = ""
    uniprot_id: str = ""


@dataclass
class DrugProteinLink:
    protein: Protein
    relation: str  # "target" | "metabolised by" | "transported by" | "inhibits" | "induces"
    action: str = ""  # e.g. "inhibitor" for targets
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class DrugProfile:
    query: str
    name: str = ""  # normalised generic name, lower case
    chembl_id: str = ""
    rxcui: str = ""
    description: str = ""
    links: list[DrugProteinLink] = field(default_factory=list)
    food_evidence: list[Evidence] = field(default_factory=list)  # label sentences that mention food, drink or meals
    boxed_warning: str = ""
    label_url: str = ""
    sources: list[SourceStatus] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.name)


@dataclass
class FoodEffect:
    protein: str  # gene symbol, or "absorption" for chelation and similar physical effects
    action: str  # "inhibits" | "induces" | "is the substrate of" | "opposes" | "binds the drug in the gut"
    note: str = ""
    url: str = ""  # citation


@dataclass
class FoodFactor:
    key: str  # "grapefruit"
    label: str  # "Grapefruit"
    component: str  # "furanocoumarins"
    terms: list[str] = field(default_factory=list)  # ingredient words that indicate this factor
    effects: list[FoodEffect] = field(default_factory=list)


@dataclass
class Interaction:
    """One path: food factor -> protein <- drug."""

    drug: str
    food: str  # FoodFactor.label
    component: str
    via: str  # protein symbol or "absorption"
    food_action: str
    drug_relation: str
    consequence: str  # plain-language outcome
    advice: str  # "avoid" | "separate by hours" | "keep intake consistent" | "monitor"
    label_confirms: bool = False  # the drug's FDA label itself mentions this food
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class InteractionReport:
    drugs: list[DrugProfile] = field(default_factory=list)
    factors: list[FoodFactor] = field(default_factory=list)  # food factors found in the product
    interactions: list[Interaction] = field(default_factory=list)
    sources: list[SourceStatus] = field(default_factory=list)


@dataclass
class Signal:
    """One local public-health reading."""

    name: str  # "Influenza", "COVID-19", ...
    level: str  # "low" | "moderate" | "high" | "very high" | "unknown"
    trend: str = ""  # "rising" | "falling" | "steady" | ""
    detail: str = ""
    as_of: str = ""
    url: str = ""


@dataclass
class LocalBriefing:
    state: str  # two-letter code
    recalls: list[Recall] = field(default_factory=list)  # match="area"
    signals: list[Signal] = field(default_factory=list)
    sources: list[SourceStatus] = field(default_factory=list)


def to_dict(obj) -> dict:
    return asdict(obj)

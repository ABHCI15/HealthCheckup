"""Curated table of well-established food effects on drug-handling proteins, and a matcher."""

from __future__ import annotations

import re

from .models import FoodEffect, FoodFactor

_GRAPEFRUIT_URL = "https://www.fda.gov/consumers/consumer-updates/grapefruit-juice-and-some-drugs-dont-mix"

FACTORS: list[FoodFactor] = [
    FoodFactor(
        "grapefruit", "Grapefruit", "furanocoumarins",
        ["grapefruit", "pomelo", "seville orange", "bitter orange"],
        [FoodEffect("CYP3A4", "inhibits",
                    "Furanocoumarins in grapefruit switch off CYP3A4 in the gut wall, the enzyme that breaks down many medicines.",
                    _GRAPEFRUIT_URL)],
    ),
    FoodFactor(
        "vitamin_k", "Vitamin K rich greens", "vitamin K",
        ["spinach", "kale", "collard", "collard green", "swiss chard", "broccoli", "brussels sprout", "parsley",
         "vitamin k", "vitamin k1", "phylloquinone", "natto"],
        [FoodEffect("VKORC1", "is the substrate of",
                    "VKORC1 recycles vitamin K so the body can make clotting factors; more vitamin K in the diet means more clotting activity.")],
    ),
    FoodFactor(
        "tyramine", "Aged and fermented foods", "tyramine",
        ["aged cheese", "cheddar", "parmesan", "blue cheese", "salami", "soy sauce", "miso", "sauerkraut", "kimchi",
         "tyramine"],
        [FoodEffect("MAOA", "is the substrate of",
                    "Tyramine from aged and fermented foods is normally broken down by monoamine oxidase A in the gut and liver."),
         FoodEffect("MAOB", "is the substrate of",
                    "Tyramine is also broken down by monoamine oxidase B.")],
    ),
    FoodFactor(
        "caffeine", "Caffeine", "caffeine",
        ["caffeine", "coffee", "espresso", "tea", "guarana", "yerba mate", "cola", "energy drink"],
        [FoodEffect("CYP1A2", "is the substrate of", "Caffeine is cleared from the body mainly by the liver enzyme CYP1A2.")],
    ),
    FoodFactor(
        "alcohol", "Alcohol", "ethanol",
        ["alcohol", "ethanol", "wine", "beer", "liquor", "vodka", "whiskey", "whisky", "rum"],
        [FoodEffect("CYP2E1", "induces", "Regular alcohol use increases the amount of the liver enzyme CYP2E1.")],
    ),
    FoodFactor(
        "dairy_calcium", "Dairy and calcium", "calcium",
        ["milk", "yogurt", "yoghurt", "cheese", "dairy", "calcium carbonate", "calcium", "calcium-fortified"],
        [FoodEffect("absorption", "binds the drug in the gut",
                    "Calcium can bind some medicines in the gut so less of the medicine is absorbed.")],
    ),
    FoodFactor(
        "iron", "Iron", "iron",
        ["iron", "ferrous", "ferrous sulfate", "ferrous fumarate", "ferrous gluconate"],
        [FoodEffect("absorption", "binds the drug in the gut",
                    "Iron can bind some medicines in the gut so less of the medicine is absorbed.")],
    ),
    FoodFactor(
        "licorice", "Licorice", "glycyrrhizin",
        ["licorice", "liquorice", "glycyrrhizin", "glycyrrhiza", "glycyrrhizic acid"],
        [FoodEffect("HSD11B2", "inhibits",
                    "Glycyrrhizin in real licorice blocks the enzyme 11-beta-HSD2, which makes the body hold on to salt and lose potassium.")],
    ),
    FoodFactor(
        "st_johns_wort", "St John's wort", "hyperforin",
        ["st john's wort", "st. john's wort", "st johns wort", "st. johns wort", "hypericum", "hyperforin"],
        [FoodEffect("CYP3A4", "induces", "Hyperforin in St John's wort makes the body produce more CYP3A4, so many medicines are broken down faster."),
         FoodEffect("ABCB1", "induces", "St John's wort also increases P-glycoprotein (ABCB1), a pump that pushes medicines out of the body.")],
    ),
    FoodFactor(
        "cruciferous_chargrilled", "Cruciferous vegetables and char-grilled meat", "indoles and polycyclic aromatic hydrocarbons",
        ["broccoli", "brussels sprout", "cabbage", "cauliflower", "char-grilled", "chargrilled", "charbroiled"],
        [FoodEffect("CYP1A2", "induces", "Cruciferous vegetables and char-grilled meat increase the activity of the liver enzyme CYP1A2.")],
    ),
    FoodFactor(
        "potassium", "Potassium", "potassium",
        ["potassium", "potassium chloride", "salt substitute"],
        [FoodEffect("potassium", "adds potassium", "Potassium-rich foods and salt substitutes add to the potassium level in the blood.")],
    ),
]


def term_pattern(term: str) -> re.Pattern:
    """Whole word or whole phrase, case-insensitive, tolerant of plural endings and flexible spacing."""
    body = r"[\s\-]+".join(re.escape(part) for part in re.split(r"[\s\-]+", term.strip()) if part)
    return re.compile(rf"(?<![A-Za-z0-9]){body}(?:e?s)?(?![A-Za-z0-9])", re.I)


def mentions(text: str, terms) -> bool:
    return any(t and term_pattern(t).search(text or "") for t in terms)


def find(text: str) -> list[FoodFactor]:
    text = (text or "").replace("’", "'")
    return [f for f in FACTORS if mentions(text, f.terms)]

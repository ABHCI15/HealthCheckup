---
name: healthcheckup
description: Use when checking a food, supplement or medicine for recalls or food-drug interactions, or when explaining a drug's protein targets. Covers barcode lookups, recall checks by name, food -> protein -> drug interaction paths, and local recall and public-health briefings for a US state.
---

# HealthCheckup

Answer from the `healthcheckup` MCP server's tools, not from memory. The tools query
live sources (CPSC, FDA, USDA FSIS, FDA drug labels, drug-target databases) and report
which of them answered.

## Which tool for which question

| Question | Tool |
|---|---|
| "Is this barcode / UPC recalled?" "What is this product?" | `lookup_barcode(barcode)` |
| "Is <named product> recalled?" (no barcode) | `check_recalls(name, kind, brand)` |
| "What does <drug> act on?" "How does <drug> work?" | `drug_targets(drug)` |
| "Can I eat/drink <food> with <drugs>?" | `food_drug_interactions(food, drugs)` |
| "Anything going on in my state?" | `local_health_briefing(state)` |

## Order

1. Identify: `lookup_barcode` if there is a barcode, otherwise use the name given.
2. Recalls: already included in `lookup_barcode`; otherwise call `check_recalls`.
3. Interactions: if the product is a food and the user takes medicines, call
   `food_drug_interactions` with the product's ingredients (or name) and the drug list.
   If the product is a drug, call `drug_targets`, and `food_drug_interactions` for any
   food the user asks about.

Ask for the user's medicines if they want interaction information and have not listed any.

## Presenting results

Recalls: a match on `barcode`, `lot` or `ndc` is the user's exact product; say so first
and give the remedy. A `name` match is only possible: tell the user to compare the lot
number and dates on the package with the recall notice, and link it.

Interactions: show each one as a path, then the meaning, then the action.

    Grapefruit (furanocoumarins) -> inhibits CYP3A4 <- simvastatin is metabolised by it
    Meaning: more simvastatin stays in the blood, raising the risk of muscle damage.
    Do: avoid. Source: FDA label for simvastatin (label confirms).

Say whether the drug's own FDA label confirms the interaction (`label_confirms`).

## Rules

- Never say "safe". With no recall, say "no recall found in the sources that answered"
  and list those sources. With no interaction, say "no interaction found in the sources
  checked".
- If a source has `ok: false`, or a tool returns `error`, say that source was not
  checked. Do not fold it into a "nothing found" statement.
- Always name the source of each fact, using the source names and URLs in the results.
- This is information, not medical advice. End with a suggestion to confirm with a
  pharmacist when the user is deciding what to take or eat.

"""Experimental structures of a drug bound to its protein target, drawn with py2Dmol.

The table is curated and small on purpose: each entry was checked against the RCSB entry title
and its ligand list. A pair that is not listed returns nothing rather than a guess.
"""

from __future__ import annotations

from functools import lru_cache

# (drug, gene symbol) -> RCSB entry in which that drug is bound to that protein.
BOUND: dict[tuple[str, str], dict] = {
    ("simvastatin", "HMGCR"): {
        "pdb": "1HW9",
        "ligand": "SIM",
        "ligand_name": "simvastatin (acid form)",
        "title": "Catalytic portion of human HMG-CoA reductase with simvastatin",
        "method": "X-ray diffraction, 2.33 Å",
        "doi": "10.1126/science.1059344",
        "note": "The statin sits in the pocket where the enzyme's own substrate, HMG-CoA, would bind.",
    },
    ("warfarin", "VKORC1"): {
        "pdb": "6WV3",
        "ligand": "SWF",
        "ligand_name": "S-warfarin",
        "title": "Human vitamin K epoxide reductase (VKOR) with warfarin",
        "method": "X-ray diffraction, 2.2 Å",
        "doi": "10.1126/science.abc5667",
        "note": "Warfarin occupies the pocket that vitamin K uses. The crystallised protein includes a fused fluorescent protein that is not part of VKOR.",
    },
}
_BY_PDB = {entry["pdb"]: entry for entry in BOUND.values()}


def lookup(drug: str, symbol: str) -> dict | None:
    entry = BOUND.get((drug.strip().lower(), symbol.strip().upper()))
    if entry is None:
        return None
    return {**entry, "drug": drug.strip().lower(), "symbol": symbol.strip().upper(),
            "rcsb_url": f"https://www.rcsb.org/structure/{entry['pdb']}", "paper_url": f"https://doi.org/{entry['doi']}"}


def for_drug(drug: str) -> list[dict]:
    """Every curated bound structure for one drug."""
    return [lookup(d, s) for (d, s) in BOUND if d == drug.strip().lower()]


@lru_cache(maxsize=8)
def viewer_html(pdb_id: str) -> str:
    """Self-contained py2Dmol viewer page for a curated entry. Raises KeyError for anything else."""
    entry = _BY_PDB[pdb_id.upper()]
    import py2Dmol

    view = py2Dmol.view(size=(560, 460), rotate=True, shadow=True, controls=False, box=False)
    # Waters and crystallisation lipids are hidden so the drug is the only small molecule shown.
    view.from_pdb(entry["pdb"], load_ligands=True, ignore_ligands=["HOH", "OLC", "ADP"])
    # py2Dmol renders into a notebook; this is the same HTML it would display there.
    body = view._display_viewer(static_data=view.objects)
    return ("<!doctype html><html><head><meta charset='utf-8'><style>html,body{margin:0;background:#fff;"
            "display:grid;place-items:center;height:100%;overflow:hidden}</style></head><body>" + body + "</body></html>")

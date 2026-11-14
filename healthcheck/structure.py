"""Predicted 3D structure of a human protein, for the viewer and the design brief.

Gene symbol -> UniProt accession (reviewed human entry) -> AlphaFold DB model -> C-alpha trace.
"""

from __future__ import annotations

from functools import lru_cache

import requests

HEADERS = {"User-Agent": "healthcheckup/0.1"}
TIMEOUT = 15


@lru_cache(maxsize=64)
def _fetch(symbol: str) -> dict:
    r = requests.get(
        "https://rest.uniprot.org/uniprotkb/search",
        params={"query": f"gene_exact:{symbol} AND organism_id:9606 AND reviewed:true",
                "fields": "accession,protein_name,length", "format": "json", "size": 1},
        headers=HEADERS, timeout=TIMEOUT,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        raise LookupError(f"No reviewed human UniProt entry for gene {symbol}.")
    entry = results[0]
    accession = entry["primaryAccession"]
    description = entry.get("proteinDescription", {})
    name = description.get("recommendedName", {}).get("fullName", {}).get("value", "")

    r = requests.get(f"https://alphafold.ebi.ac.uk/api/prediction/{accession}", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    models = r.json()
    if not models:
        raise LookupError(f"AlphaFold DB has no model for {accession}.")
    model = models[0]
    pdb = requests.get(model["pdbUrl"], headers=HEADERS, timeout=30)
    pdb.raise_for_status()

    # PDB is fixed-width: atom name in columns 13-16, coordinates in 31-54, B-factor (pLDDT here) in 61-66.
    trace = []
    for line in pdb.text.splitlines():
        if line.startswith("ATOM") and line[12:16].strip() == "CA":
            trace.append([float(line[30:38]), float(line[38:46]), float(line[46:54]), float(line[60:66])])
    if not trace:
        raise LookupError("The structure file had no C-alpha atoms.")
    return {
        "symbol": symbol,
        "accession": accession,
        "name": name,
        "length": len(trace),
        "mean_plddt": round(sum(t[3] for t in trace) / len(trace), 1),
        "confident_fraction": round(sum(1 for t in trace if t[3] >= 70) / len(trace), 2),
        "model_id": model.get("modelEntityId", ""),
        "model_url": model["pdbUrl"],
        "page_url": f"https://alphafold.ebi.ac.uk/entry/{accession}",
        "uniprot_url": f"https://www.uniprot.org/uniprotkb/{accession}",
        "source": "AlphaFold DB (predicted structure)",
        "ca": trace,
    }


def structure(symbol: str) -> dict:
    """Return the structure dict, or {"error": reason}. Failures are not cached."""
    symbol = symbol.strip().upper()
    if not symbol.replace("-", "").isalnum() or len(symbol) > 15:
        return {"error": "Enter a human gene symbol such as CYP3A4."}
    try:
        return _fetch(symbol)
    except LookupError as exc:
        return {"error": str(exc)}
    except (requests.RequestException, KeyError, ValueError) as exc:
        return {"error": f"Structure lookup failed: {exc.__class__.__name__}"}

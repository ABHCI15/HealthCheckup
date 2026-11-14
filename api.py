"""HTTP API for the React front end. Run: venv/bin/uvicorn api:app --port 8000

Serves the built front end from web/dist when it exists, so one process is enough for a demo.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from healthcheck import ai, barcode, drugs, foodmap, interactions, local, products, recalls, store, structure, watch
from healthcheck.models import to_dict

ROOT = Path(__file__).resolve().parent
UID = "guest"
app = FastAPI(title="HealthCheckup")


def _configure_ai() -> None:
    """Read ANTHROPIC_API_KEY from a .env file in the project root if the environment has none."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    try:
        lines = (ROOT / ".env").read_text().splitlines()
    except OSError:
        return
    for line in lines:
        name, _, value = line.partition("=")
        value = value.strip().strip("\"'")
        if name.strip() == "ANTHROPIC_API_KEY" and value and not value.endswith("..."):
            ai.configure(value)


_configure_ai()


def _profile(name: str):
    """Drug profile that is not cached when a source failed, so a network blip does not stick."""
    profile = drugs.profile(name)
    if any(not s.ok for s in profile.sources):
        drugs.profile.cache_clear()
    return profile


def _is_drug(name: str) -> bool:
    # Foods such as "milk" and "banana" exist in drug databases as allergen extracts,
    # so a typed name counts as a medicine only if it has protein links and is not a known food.
    if foodmap.find(name):
        return False
    profile = _profile(name)
    return profile.found and bool(profile.links)


def _drug_view(name: str) -> dict:
    data = to_dict(_profile(name))
    data["links"] = data["links"][:14]
    return data


@app.get("/api/status")
def status() -> dict:
    return {"ai": ai.available(), "meds": store.meds(UID), "state": store.state(UID) or "CA", "states": local.STATES}


@app.get("/api/scan")
def scan(q: str) -> dict:
    """Check a barcode number or a typed food or medicine name."""
    q = q.strip()
    if not q:
        raise HTTPException(400, "Enter a barcode or a name.")
    warning = ""
    code = None
    if q.replace(" ", "").replace("-", "").isdigit():
        code = barcode.parse(q)
        if code is None or not code.is_gtin:
            raise HTTPException(400, f"That is not a product barcode. {code.note if code else ''}".strip())
        if not code.checksum_ok:
            warning = f"{code.note}. Results may be for the wrong product."
        product = products.identify(code)
    else:
        product = products.from_name(q, "drug" if _is_drug(q) else "food")

    report = recalls.check(product, code)
    out = {"product": {**to_dict(product), "title": product.title}, "recalls": to_dict(report), "warning": warning,
           "interactions": None, "drug": None}
    meds = store.meds(UID)
    if product.kind == "drug":
        out["drug"] = _drug_view(product.generic_name or product.name)
    elif product.kind == "food" and meds:
        food_text = " ".join([product.name, product.ingredients, " ".join(product.categories)])
        result = interactions.analyze(food_text, meds)
        if any(not s.ok for s in result.sources):
            drugs.profile.cache_clear()
        data = to_dict(result)
        for profile in data["drugs"]:  # The front end needs links for the graph, not the label text.
            profile["links"] = profile["links"][:8]
            profile["food_evidence"] = []
        out["interactions"] = data
    return out


class Meds(BaseModel):
    meds: list[str]


@app.put("/api/meds")
def set_meds(body: Meds) -> dict:
    store.set_meds(UID, body.meds)
    return {"meds": store.meds(UID)}


@app.get("/api/drug/{name}")
def drug(name: str) -> dict:
    return _drug_view(name)


@app.get("/api/local/{state}")
def near_me(state: str) -> dict:
    state = state.upper()
    if state not in local.STATES:
        raise HTTPException(400, "Unknown state code.")
    store.set_state(UID, state)
    brief = local.briefing(state)
    if any(not s.ok for s in brief.sources):
        local.briefing.cache_clear()
    return to_dict(brief)


@app.get("/api/watchlist")
def watchlist() -> dict:
    return {"items": [{**to_dict(p), "title": p.title} for p in store.items(UID)], "alerts": store.alerts(UID)[:30],
            "last_check": store.last_check(UID), "meds": store.meds(UID)}


class Item(BaseModel):
    product: dict


@app.post("/api/watchlist")
def save_item(body: Item) -> dict:
    added = store.add_item(UID, store._product(body.product))
    return {"added": added}


@app.delete("/api/watchlist/{key}")
def remove_item(key: str) -> dict:
    store.remove_item(UID, key)
    return {"ok": True}


@app.post("/api/watch/run")
def run_watch() -> dict:
    new = watch.run_once(UID)
    return {"new": [to_dict(r) for r in new], "last_check": store.last_check(UID)}


class Explain(BaseModel):
    product: dict
    recalls: dict
    interactions: dict | None = None


@app.post("/api/explain")
def explain(body: Explain):
    if not ai.available():
        raise HTTPException(503, "No Anthropic API key is configured.")

    def stream():
        try:
            yield from ai.explain(body.product, body.recalls, body.interactions or {})
        except Exception as exc:  # Surface the reason in the stream instead of dropping the connection.
            yield f"\n[Claude could not finish: {exc}]"

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


class Chat(BaseModel):
    messages: list[dict]


@app.post("/api/chat")
def chat(body: Chat) -> dict:
    if not ai.available():
        raise HTTPException(503, "No Anthropic API key is configured.")
    used: list[dict] = []
    try:
        answer = "".join(ai.chat(body.messages, on_tool=lambda name, args: used.append({"name": name, "input": args})))
    except Exception as exc:
        raise HTTPException(502, str(exc))
    return {"answer": answer, "tools": used}


@app.get("/api/targets")
def targets() -> dict:
    """Proteins linked to the user's medicines, as candidates for the structure viewer."""
    out: list[dict] = []
    for med in store.meds(UID):
        for link in _profile(med).links:
            if not any(t["symbol"] == link.protein.symbol for t in out):
                out.append({"symbol": link.protein.symbol, "name": link.protein.name, "drug": med, "relation": link.relation})
    return {"targets": out[:16]}


@app.get("/api/structure/{symbol}")
def protein_structure(symbol: str) -> dict:
    data = structure.structure(symbol)
    if "error" in data:
        raise HTTPException(404, data["error"])
    return data


DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        return FileResponse(DIST / "index.html")

# HealthCheckup

Scan what you eat or take. HealthCheckup checks it against government recalls and shows how it
interacts with your medicines at the protein level: food component → protein ← drug.

Demo video: [demo/healthcheckup-demo.webm](demo/healthcheckup-demo.webm)

## Run it

```bash
python3.12 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env                     # add your Anthropic API key
cd web && npm install && npm run build && cd ..
venv/bin/uvicorn api:app --port 8000     # open http://127.0.0.1:8000
```

For front-end development run `npm run dev` in `web/` (port 5173, proxies `/api` to port 8000).
Without an API key everything except the Claude features (summary, chat) still works.

## What is in here

| Path | What it does |
|---|---|
| `web/` | React front end built with Vite; Playwright tests in `web/tests` |
| `web/src/Graph.jsx` | Food → protein ← medicine interaction graph |
| `web/src/Protein3D.jsx` | three.js viewer for a target protein's predicted structure |
| `api.py` | FastAPI server for the front end; also serves the built app |
| `healthcheck/barcode.py` | Barcode normalisation (UPC, EAN, GS1) and photo decoding |
| `healthcheck/products.py` | Identify a barcode: openFDA drug labels and NDC, Open Food Facts |
| `healthcheck/recalls.py` | Recalls from CPSC, FDA food and FDA drug; USDA FSIS reported as unavailable |
| `healthcheck/drugs.py` | Drug targets from Open Targets, enzymes and food warnings from the FDA label, RxNorm |
| `healthcheck/foodmap.py` | Curated table of food components and the proteins they act on |
| `healthcheck/interactions.py` | Joins food effects and drug proteins into interactions |
| `healthcheck/structure.py` | Gene symbol → UniProt → AlphaFold DB structure |
| `healthcheck/local.py` | Recalls distributed in a state, CDC respiratory illness activity |
| `healthcheck/watch.py` | Scheduler that re-checks saved products and medicines for new recalls |
| `healthcheck/ai.py`, `tools.py` | Claude: summary and a tool-using agent |
| `mcp_server.py`, `.mcp.json` | The same five tools as an MCP server |
| `.claude/skills/healthcheckup/` | Claude Code skill that uses the MCP tools |

## Scheduler

```bash
venv/bin/python -m healthcheck.watch              # once
venv/bin/python -m healthcheck.watch --every 360  # every 6 hours
```

## Tests

```bash
venv/bin/python -m pytest tests -q        # offline unit tests
cd web && npx playwright test             # end to end, against live data sources
```

## Limits

- Information from public sources, not medical advice.
- The food table covers 11 well-established food effects.
- USDA FSIS (meat, poultry, eggs) refuses automated access, so those recalls are linked, not checked.
- The Protein design tab prepares a target and a job brief. No design engine is connected, so it
  does not generate designs.
- The demo uses barcodes coded into the page. Camera scanning is not wired into the React app;
  the photo decoder in `healthcheck/barcode.py` is tested on generated images only.
- Sign-in from the original app is switched off; data is stored locally in `.data/` for one guest user.

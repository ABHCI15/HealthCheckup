import { useEffect, useState } from "react";
import { api } from "./api.js";
import Barcode from "./Barcode.jsx";
import Graph from "./Graph.jsx";
import Protein3D from "./Protein3D.jsx";

// Barcodes coded in for the demo. Each is a real product code that the live sources recognise.
const CODED = [
  { code: "0025000051753", name: "Simply Grapefruit juice", note: "Food · meets statins at CYP3A4" },
  { code: "0826520107322", name: "Kale and spinach salad", note: "Food · meets warfarin at VKORC1, with the drug-bound structure" },
  { code: "840059614922", name: "Hampton Bay ceiling fan", note: "Recalled by CPSC" },
  { code: "810123980659", name: "Blue Bottle blossom syrup", note: "Recalled by FDA" },
];
const TABS = ["Scan", "My medicines", "Protein design", "Watchlist", "Near me", "Ask Claude"];
const QUICK_MEDS = ["simvastatin", "warfarin", "phenelzine", "ciprofloxacin"];

function Sources({ sources = [] }) {
  const ok = [...new Set(sources.filter((s) => s.ok).map((s) => s.source))];
  const bad = sources.filter((s) => !s.ok);
  if (!sources.length) return null;
  return (
    <div className="sources">
      {ok.length > 0 && <p>Checked: {ok.join(" · ")}</p>}
      {bad.map((s) => (
        <p key={s.source} className="not-checked">
          Not checked: <b>{s.source}</b>. {s.detail} {s.url && <a href={s.url} target="_blank" rel="noreferrer">Open site</a>}
        </p>
      ))}
    </div>
  );
}

function RecallCard({ r }) {
  return (
    <article className="recall">
      <header>
        <h4>{r.title || r.recall_id}</h4>
        {r.classification && <span className={`tag ${r.classification === "Class I" ? "red" : "amber"}`}>{r.classification}</span>}
      </header>
      <p className="meta">{[r.source, r.date, r.firm, r.status].filter(Boolean).join(" · ")}</p>
      {r.reason && <p>{r.reason}</p>}
      {r.remedy && <p><b>What to do:</b> {r.remedy}</p>}
      {r.match_detail && <p className="meta">Why this matched: {r.match_detail}</p>}
      {r.url && <a href={r.url} target="_blank" rel="noreferrer">Official notice</a>}
    </article>
  );
}

function Recalls({ report }) {
  const confirmed = report.recalls.filter((r) => ["barcode", "lot", "ndc"].includes(r.match));
  const possible = report.recalls.filter((r) => !confirmed.includes(r));
  const answered = report.sources.filter((s) => s.ok).length;
  return (
    <section>
      <h3>Recalls</h3>
      {confirmed.length > 0 ? (
        <div className="banner danger" data-testid="recalled"><b>Recalled.</b> {confirmed.length} recall notice{confirmed.length > 1 ? "s" : ""} match this product’s own code.</div>
      ) : possible.length > 0 ? (
        <div className="banner warn">No recall matches this exact code, but similar products were recalled. Compare the details below.</div>
      ) : (
        <div className="banner info" data-testid="no-recall">No recall found in the {answered} source{answered === 1 ? "" : "s"} that answered. That is not a guarantee the product is safe.</div>
      )}
      {confirmed.map((r) => <RecallCard key={r.source + r.recall_id} r={r} />)}
      {possible.length > 0 && (
        <details open={confirmed.length === 0}>
          <summary>Similar products recalled ({possible.length})</summary>
          {possible.map((r) => <RecallCard key={r.source + r.recall_id} r={r} />)}
        </details>
      )}
      <Sources sources={report.sources} />
    </section>
  );
}

const viaLabel = (via) => ({ absorption: "absorption in the gut", label: "FDA label warning", potassium: "potassium level" })[via] || via;
const isProtein = (via) => !["absorption", "label", "potassium"].includes(via);

function Interactions({ report, title, onTarget }) {
  const missing = report.drugs.filter((d) => !d.name).map((d) => d.query);
  // MAOA and MAOB style pairs say the same thing twice; show them as one card.
  const groups = [];
  for (const i of report.interactions) {
    const found = groups.find((g) => g.drug === i.drug && g.food === i.food && g.consequence === i.consequence);
    if (found) found.vias.push(i.via);
    else groups.push({ ...i, vias: [i.via] });
  }
  return (
    <section>
      <h3>With your medicines</h3>
      {missing.length > 0 && <p className="meta">Not recognised as a medicine: {missing.join(", ")}</p>}
      {groups.length === 0 ? (
        <div className="banner info" data-testid="no-interaction">
          {report.factors.length === 0
            ? `No known interacting food component was recognised in ${title}.`
            : `Found ${report.factors.map((f) => f.label).join(", ")}, but no shared protein or label warning links it to your medicines in the sources checked.`}
        </div>
      ) : (
        <>
          <div className="graph-card"><Graph report={report} /></div>
          <p className="meta">Gold marks the protein where the food and the medicine meet. Grey proteins are the medicine’s other targets, which this food does not touch.</p>
          {groups.map((i, n) => (
            <article className="interaction" key={n} data-testid="interaction">
              <div className="path">
                <span className="chip food">{i.food}</span>
                <span className="verb">{i.food_action} →</span>
                <span className="chip protein">{i.vias.map(viaLabel).join(", ")}</span>
                <span className="verb">← {i.drug_relation}</span>
                <span className="chip drug">{i.drug}</span>
              </div>
              <div className="outcome">
                <p>{i.consequence}</p>
                <div className="tags">
                  <span className={`tag ${i.advice === "avoid" ? "red" : i.advice === "monitor" ? "blue" : "amber"}`}>{i.advice}</span>
                  {i.label_confirms && <span className="tag green">On the FDA label</span>}
                </div>
              </div>
              <details>
                <summary>Evidence</summary>
                <ul>
                  {i.evidence.map((e, k) => (
                    <li key={k}><b>{e.source}:</b> {e.text} {e.url && <a href={e.url} target="_blank" rel="noreferrer">source</a>}</li>
                  ))}
                </ul>
                {i.vias.filter(isProtein).map((v) => (
                  <p key={v} className="meta">
                    {v}: <button className="link" onClick={() => onTarget(v, i.drug)}>see where {i.drug} meets {v} in 3D</button>{" · "}<a href={`https://www.uniprot.org/uniprotkb?query=gene_exact:${v}+AND+organism_id:9606`} target="_blank" rel="noreferrer">UniProt</a>
                    {" · "}
                    <a href={`https://alphafold.ebi.ac.uk/search/text/${v}?organismScientificName=Homo%20sapiens`} target="_blank" rel="noreferrer">structure on AlphaFold DB</a>
                  </p>
                ))}
              </details>
            </article>
          ))}
        </>
      )}
      <Sources sources={report.sources} />
    </section>
  );
}

function DrugPanel({ drug }) {
  if (!drug.name) return <div className="banner warn">Not found in Open Targets or the FDA label database. Check the spelling.</div>;
  return (
    <div className="drug">
      {drug.description && <p>{drug.description}</p>}
      {drug.boxed_warning && <div className="banner warn">{drug.boxed_warning}</div>}
      {drug.links.length > 0 && (
        <table>
          <thead><tr><th>Protein</th><th>Relation</th><th>Source</th></tr></thead>
          <tbody>
            {drug.links.map((l, i) => (
              <tr key={i}>
                <td><b>{l.protein.symbol}</b> <span className="meta">{l.protein.name}</span></td>
                <td>{l.relation === "target" && l.action ? `target (${l.action.toLowerCase()})` : l.relation}</td>
                <td className="meta">{l.evidence[0]?.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {drug.food_evidence.length > 0 && (
        <>
          <h4>What its FDA label says about food and drink</h4>
          <ul>{drug.food_evidence.slice(0, 5).map((e, i) => <li key={i}>{e.text}</li>)}</ul>
        </>
      )}
      <p className="meta">
        {drug.label_url && <a href={drug.label_url} target="_blank" rel="noreferrer">FDA label</a>}
        {drug.chembl_id && <> · <a href={`https://platform.opentargets.org/drug/${drug.chembl_id}`} target="_blank" rel="noreferrer">Open Targets</a></>}
      </p>
      <Sources sources={drug.sources} />
    </div>
  );
}

function ClaudeSummary({ result, enabled }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setText("");
    setError("");
    if (!enabled) return;
    api.explain({ product: result.product, recalls: result.recalls, interactions: result.interactions }, setText).catch((e) => setError(e.message));
  }, [result, enabled]);
  if (!enabled) return <p className="meta">Add an Anthropic API key to .env and restart to have Claude explain this result.</p>;
  return (
    <section className="claude">
      <h3>Claude’s summary</h3>
      {error ? <p className="meta">{error}</p> : <p className="claude-text">{text || "Reading the evidence…"}</p>}
    </section>
  );
}

function MedsEditor({ meds, onChange }) {
  const [draft, setDraft] = useState("");
  const add = (names) => onChange([...meds, ...names.map((n) => n.trim().toLowerCase()).filter((n) => n && !meds.includes(n))]);
  return (
    <div className="meds-editor">
      <div className="chips">
        {meds.map((m) => (
          <span className="chip drug removable" key={m}>{m}<button aria-label={`Remove ${m}`} onClick={() => onChange(meds.filter((x) => x !== m))}>×</button></span>
        ))}
        {meds.length === 0 && <span className="meta">No medicines yet.</span>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); add(draft.split(",")); setDraft(""); }}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Add a medicine" aria-label="Add a medicine" />
        <button className="btn ghost" type="submit">Add</button>
      </form>
      <div className="quick">
        {QUICK_MEDS.filter((m) => !meds.includes(m)).map((m) => <button key={m} className="pill" onClick={() => add([m])}>+ {m}</button>)}
      </div>
    </div>
  );
}

function ScanTab({ status, setMeds, onTarget }) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [saved, setSaved] = useState("");
  const [photo, setPhoto] = useState(null);

  const onPhoto = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // Allow choosing the same photo again.
    if (!file) return;
    setPhoto({ busy: true }); setError(""); setResult(null);
    try {
      const read = await api.decode(file);
      setPhoto(read);
      if (read.found) run(read.code);
    } catch (err) {
      setPhoto({ found: false, hint: err.message });
    }
  };

  const run = async (q) => {
    setBusy(q); setError(""); setSaved("");
    try {
      setResult(await api.scan(q));
    } catch (e) {
      setError(e.message); setResult(null);
    } finally {
      setBusy("");
    }
  };
  const p = result?.product;

  return (
    <div className="scan">
      <aside>
        <div className="panel">
          <h3>Your medicines</h3>
          <MedsEditor meds={status.meds} onChange={setMeds} />
        </div>
        <div className="panel">
          <h3>Scan a product</h3>
          <label className="photo-drop">
            <input type="file" accept="image/*" capture="environment" onChange={onPhoto} data-testid="photo-input" />
            <span className="photo-title">Scan from a photo</span>
            <span className="meta">Take or choose a photo of the barcode. It is read on the server.</span>
          </label>
          {photo && (
            <p className={`photo-result${photo.found ? " ok" : ""}`} data-testid="photo-result" role="status">
              {photo.busy ? "Reading the barcode from the photo…"
                : photo.found ? `Read ${photo.symbology} ${photo.code}${photo.stage && photo.stage !== "original" ? ` (needed: ${photo.stage})` : ""}${photo.checksum_ok ? "" : ". " + photo.note}`
                : `${photo.hint}${photo.stages_tried ? ` Tried ${photo.stages_tried} image treatments.` : ""}`}
            </p>
          )}
          <p className="meta or">or use a coded demo barcode</p>
          <div className="coded">
            {CODED.map((c) => (
              <button key={c.code} className={`coded-card${busy === c.code ? " busy" : ""}`} onClick={() => run(c.code)} disabled={!!busy} data-testid={`scan-${c.code}`}>
                <Barcode code={c.code} />
                <span className="digits">{c.code}</span>
                <span className="coded-name">{c.name}</span>
                <span className="meta">{c.note}</span>
              </button>
            ))}
          </div>
          <form className="typed" onSubmit={(e) => { e.preventDefault(); if (query.trim()) run(query.trim()); }}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Barcode number, or a food or medicine name" aria-label="Barcode or name" />
            <button className="btn" type="submit" disabled={!!busy}>Check</button>
          </form>
        </div>
      </aside>

      <main>
        {busy && <div className="loading"><span className="scanner" />Identifying the product, checking recalls and comparing proteins…</div>}
        {error && <div className="banner danger">{error}</div>}
        {!busy && !result && !error && (
          <div className="empty">
            <h2>Scan it. See the protein. Know what to do.</h2>
            <p>Pick a coded barcode on the left, or type a food. Results are checked against your medicines and against FDA and CPSC recalls.</p>
          </div>
        )}
        {!busy && result && (
          <div className="result">
            {result.warning && <div className="banner warn">{result.warning}</div>}
            <article className="product">
              {p.image_url && <img src={p.image_url} alt="" />}
              <div>
                <h2 data-testid="product-title">{p.title}</h2>
                <p className="meta">{[p.kind === "unknown" ? "Not in our product sources" : p.kind, p.barcode && `Barcode ${p.barcode}`, p.source].filter(Boolean).join(" · ")}</p>
                {p.ingredients && <p className="meta">Ingredients: {p.ingredients.slice(0, 240)}</p>}
                <button className="btn ghost" onClick={async () => setSaved((await api.save(p)).added ? "Saved. The scheduler will re-check it." : "Already on your watchlist.")}>Save to watchlist</button>
                {saved && <span className="meta"> {saved}</span>}
              </div>
            </article>
            <Recalls report={result.recalls} />
            {result.interactions && <Interactions report={result.interactions} title={p.title} onTarget={onTarget} />}
            {p.kind === "food" && !result.interactions && <p className="meta">Add your medicines on the left to see how this food interacts with them.</p>}
            {result.drug && <section><h3>What this medicine acts on</h3><DrugPanel drug={result.drug} /></section>}
            <ClaudeSummary result={result} enabled={status.ai} />
          </div>
        )}
      </main>
    </div>
  );
}

function MedsTab({ status, setMeds }) {
  const [open, setOpen] = useState("");
  const [details, setDetails] = useState({});
  const toggle = async (m) => {
    setOpen(open === m ? "" : m);
    if (!details[m]) {
      try {
        const d = await api.drug(m);
        setDetails((x) => ({ ...x, [m]: d }));
      } catch (e) {
        setDetails((x) => ({ ...x, [m]: { error: e.message } }));
      }
    }
  };
  return (
    <div className="page">
      <h2>My medicines</h2>
      <p className="meta">Stored on this computer only. Used to check every food you scan, and watched for recalls.</p>
      <div className="panel"><MedsEditor meds={status.meds} onChange={setMeds} /></div>
      {status.meds.map((m) => (
        <div className="panel" key={m}>
          <button className="row-toggle" onClick={() => toggle(m)}>{m}<span>{open === m ? "Hide" : "Targets and label"}</span></button>
          {open === m && (details[m] ? (details[m].error ? <p className="meta">{details[m].error}</p> : <DrugPanel drug={details[m]} />) : <p className="meta">Loading…</p>)}
        </div>
      ))}
    </div>
  );
}

function WatchTab() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const load = () => api.watchlist().then(setData);
  useEffect(() => { load(); }, []);
  if (!data) return <div className="page"><p className="meta">Loading…</p></div>;
  const check = async () => {
    setBusy(true); setNote("");
    try {
      const r = await api.runWatch();
      setNote(r.new.length ? `${r.new.length} new recall alert(s).` : "No new recalls.");
      await load();
    } catch (e) {
      setNote(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h2>Watchlist</h2>
          <p className="meta">{data.items.length} product(s) and {data.meds.length} medicine(s) are re-checked for new recalls. {data.last_check ? `Last check ${data.last_check.slice(0, 16).replace("T", " ")} UTC.` : "Not checked yet."}</p>
        </div>
        <button className="btn" onClick={check} disabled={busy}>{busy ? "Checking…" : "Check now"}</button>
      </div>
      {note && <div className="banner info">{note}</div>}
      {data.alerts.length > 0 && <h3>Alerts</h3>}
      {data.alerts.map((a) => <RecallCard key={a.source + a.recall_id} r={a} />)}
      <h3>Saved products</h3>
      {data.items.length === 0 && <p className="meta">Nothing saved yet. Scan a product and choose Save to watchlist.</p>}
      {data.items.map((i) => (
        <div className="panel saved" key={i.barcode || i.title}>
          <div><b>{i.title}</b><p className="meta">{[i.kind, i.barcode].filter(Boolean).join(" · ")}</p></div>
          <button className="btn ghost" onClick={async () => { await api.remove(i.barcode || i.title); load(); }}>Remove</button>
        </div>
      ))}
      <h3>Run it on a schedule</h3>
      <pre>venv/bin/python -m healthcheck.watch --every 360</pre>
    </div>
  );
}

function LocalTab({ status }) {
  const [state, setState] = useState(status.state);
  const [brief, setBrief] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setBrief(null); setError("");
    api.local(state).then(setBrief).catch((e) => setError(e.message));
  }, [state]);
  return (
    <div className="page">
      <div className="page-head">
        <h2>Near me</h2>
        <select value={state} onChange={(e) => setState(e.target.value)} aria-label="State">
          {Object.entries(status.states).map(([code, name]) => <option key={code} value={code}>{name}</option>)}
        </select>
      </div>
      {error && <div className="banner danger">{error}</div>}
      {!brief && !error && <p className="meta">Loading recalls and public-health signals…</p>}
      {brief && (
        <>
          {brief.signals.length > 0 && <h3>Illness activity</h3>}
          <div className="signals">
            {brief.signals.map((s) => (
              <div className="signal" key={s.name} data-testid="signal">
                <h4>{s.name}</h4>
                {s.level !== "unknown" && <span className={`tag ${s.level === "low" ? "green" : s.level === "moderate" ? "amber" : "red"}`}>{s.level}</span>}
                {s.trend && <span className={`tag ${s.trend === "rising" ? "amber" : "blue"}`}>{s.trend}</span>}
                <p className="meta">{s.detail}</p>
                {s.as_of && <p className="meta">Week ending {s.as_of}</p>}
              </div>
            ))}
          </div>
          <h3>Recalls distributed in {status.states[state]}, last 30 days</h3>
          {brief.recalls.length === 0 && <div className="banner info">No recalls returned for this state in the sources that answered.</div>}
          {brief.recalls.map((r) => <RecallCard key={r.source + r.recall_id} r={r} />)}
          <Sources sources={brief.sources} />
        </>
      )}
    </div>
  );
}

function ChatTab({ status }) {
  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  if (!status.ai) {
    return <div className="page"><h2>Ask Claude</h2><div className="banner info">Add an Anthropic API key to .env and restart the server to enable the assistant.</div></div>;
  }
  const send = async (e) => {
    e.preventDefault();
    if (!draft.trim() || busy) return;
    const next = [...messages, { role: "user", content: draft.trim() }];
    setMessages(next); setDraft(""); setBusy(true);
    try {
      const r = await api.chat(next.map(({ role, content }) => ({ role, content })));
      setMessages([...next, { role: "assistant", content: r.answer, tools: r.tools }]);
    } catch (err) {
      setMessages([...next, { role: "assistant", content: `Claude could not answer: ${err.message}` }]);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="page chat">
      <h2>Ask Claude</h2>
      <p className="meta">Claude answers with live lookups against FDA, CPSC, Open Targets and RxNorm, not from memory.</p>
      {messages.map((m, i) => (
        <div key={i} className={`bubble ${m.role}`}>
          {m.tools?.length > 0 && <p className="meta">Looked up: {m.tools.map((t) => t.name).join(", ")}</p>}
          {m.content}
        </div>
      ))}
      {busy && <div className="bubble assistant meta">Looking things up…</div>}
      <form onSubmit={send}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Can I drink grapefruit juice with simvastatin?" aria-label="Question" />
        <button className="btn" type="submit" disabled={busy}>Ask</button>
      </form>
    </div>
  );
}

function DesignTab({ target, setTarget, drug, setDrug }) {
  const [targets, setTargets] = useState([]);
  const [draft, setDraft] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [goal, setGoal] = useState("binder");
  const [length, setLength] = useState("60-100");
  const [bound, setBound] = useState({ match: null, others: [] });

  useEffect(() => {
    setBound({ match: null, others: [] });
    if (target && drug) api.binding(drug, target).then(setBound).catch(() => {});
  }, [target, drug]);
  useEffect(() => { api.targets().then((r) => setTargets(r.targets)).catch(() => setTargets([])); }, []);
  useEffect(() => {
    if (!target) return;
    setData(null); setError("");
    api.structure(target).then(setData).catch((e) => setError(e.message));
  }, [target]);

  const brief = data && {
    schema: "healthcheckup.design-brief/1",
    status: "not submitted: no design engine is connected in this build",
    target: { gene: data.symbol, protein: data.name, uniprot: data.accession, residues: data.length },
    structure: { source: data.source, model: data.model_id, url: data.model_url, mean_plddt: data.mean_plddt },
    objective: goal === "binder" ? "de novo protein binder to the target surface" : "de novo binder that blocks the active site",
    binder_length: length,
    hotspot_residues: "to be chosen by a structural biologist",
    intended_engine: "RFdiffusion-family backbone generation, then sequence design and structure-prediction filtering",
    review: "research hypothesis only; requires expert review and wet-lab validation",
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(brief, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url; a.download = `design-brief-${data.symbol}.json`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="page wide">
      <h2>Protein design</h2>
      <p className="meta">Step 2 of the project. Start from an interaction: see where the medicine binds its protein, inspect the target on its own, then export the brief a design run needs.</p>
      <div className="banner warn" data-testid="design-limit">
        <b>The design engine is not connected.</b> This build prepares the target and the job brief for an RFdiffusion-family run; it does not generate or evaluate designs, and it does not diagnose anyone. Any design is a research hypothesis, not a treatment.
      </div>
      <div className="panel">
        <h3>Target</h3>
        <div className="quick">
          {targets.map((t) => (
            <button key={t.symbol} className={`pill${target === t.symbol ? " on" : ""}`} onClick={() => { setTarget(t.symbol); setDrug(t.drug); }} title={`${t.name} · ${t.relation} · ${t.drug}`}>{t.symbol}{t.bound ? " ●" : ""}</button>
          ))}
          {targets.length === 0 && <span className="meta">Add medicines to list their proteins here, or type a gene symbol.</span>}
          {targets.some((t) => t.bound) && <span className="meta">● a structure with the medicine bound is available</span>}
        </div>
        <form className="typed" onSubmit={(e) => { e.preventDefault(); if (draft.trim()) { setTarget(draft.trim().toUpperCase()); setDrug(""); } }}>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Human gene symbol, for example CYP3A4" aria-label="Gene symbol" />
          <button className="btn" type="submit">Load structure</button>
        </form>
      </div>
      {error && <div className="banner danger">{error}</div>}
      {target && !data && !error && <div className="loading"><span className="scanner" />Fetching the structure of {target} from UniProt and AlphaFold DB…</div>}
      {target && drug && (
        <section className="story">
          <h3>1 · Where {drug} binds {target}</h3>
          {bound.match ? (
            <div className="bound" data-testid="bound">
              <iframe title={`${bound.match.ligand_name} bound to ${target}`} src={`/api/binding-view/${bound.match.pdb}`} />
              <div className="panel">
                <p><b>{bound.match.title}</b></p>
                <p>{bound.match.note}</p>
                <table>
                  <tbody>
                    <tr><td>Bound molecule</td><td>{bound.match.ligand_name} ({bound.match.ligand})</td></tr>
                    <tr><td>Method</td><td>{bound.match.method}</td></tr>
                    <tr><td>Entry</td><td><a href={bound.match.rcsb_url} target="_blank" rel="noreferrer">PDB {bound.match.pdb}</a> · <a href={bound.match.paper_url} target="_blank" rel="noreferrer">paper</a></td></tr>
                  </tbody>
                </table>
                <p className="meta">Experimental structure with the medicine bound, drawn with py2Dmol. Drag to turn.</p>
              </div>
            </div>
          ) : (
            <div className="banner info" data-testid="no-bound">
              No experimental structure of {drug} bound to {target} is in our checked set, so none is shown.
              {bound.others.map((o) => (
                <span key={o.pdb}> {drug} is bound to its own target in one: <button className="link" onClick={() => setTarget(o.symbol)}>open {o.symbol}</button>.</span>
              ))}
            </div>
          )}
        </section>
      )}
      {data && <h3 className="story-head">{drug ? "2" : "1"} · The target on its own, and {drug ? "3" : "2"} · the design brief</h3>}
      {data && (
        <div className="design">
          <div className="viewer">
            <Protein3D trace={data.ca} />
            <div className="legend"><span className="sw high" />confident<span className="sw mid" />medium<span className="sw low" />low confidence<span className="hint">drag to turn · scroll to zoom</span></div>
          </div>
          <div>
            <div className="panel">
              <h3>{data.symbol}</h3>
              <p><b data-testid="structure-name">{data.name}</b></p>
              <table>
                <tbody>
                  <tr><td>UniProt</td><td><a href={data.uniprot_url} target="_blank" rel="noreferrer">{data.accession}</a></td></tr>
                  <tr><td>Residues</td><td>{data.length}</td></tr>
                  <tr><td>Mean confidence (pLDDT)</td><td>{data.mean_plddt}</td></tr>
                  <tr><td>Confident residues</td><td>{Math.round(data.confident_fraction * 100)}%</td></tr>
                  <tr><td>Model</td><td><a href={data.page_url} target="_blank" rel="noreferrer">{data.model_id}</a></td></tr>
                </tbody>
              </table>
              <p className="meta">Predicted structure from AlphaFold DB, not an experimental one.</p>
            </div>
            <div className="panel">
              <h3>Design brief</h3>
              <form className="brief-form" onSubmit={(e) => e.preventDefault()}>
                <label>Objective
                  <select value={goal} onChange={(e) => setGoal(e.target.value)}>
                    <option value="binder">Binder to the target</option>
                    <option value="blocker">Active-site blocker</option>
                  </select>
                </label>
                <label>Binder length
                  <select value={length} onChange={(e) => setLength(e.target.value)}>
                    <option>60-100</option><option>80-140</option><option>120-200</option>
                  </select>
                </label>
              </form>
              <pre data-testid="brief">{JSON.stringify(brief, null, 2)}</pre>
              <button className="btn" onClick={download}>Download brief</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [status, setStatus] = useState(null);
  const [tab, setTab] = useState("Scan");
  const [error, setError] = useState("");
  const [target, setTarget] = useState("");
  const [drug, setDrug] = useState("");
  const openTarget = (symbol, forDrug = "") => { setTarget(symbol); setDrug(forDrug); setTab("Protein design"); window.scrollTo(0, 0); };
  useEffect(() => { api.status().then(setStatus).catch((e) => setError(e.message)); }, []);
  const setMeds = async (meds) => {
    const r = await api.setMeds(meds);
    setStatus((s) => ({ ...s, meds: r.meds }));
  };
  return (
    <>
      <header className="top">
        <div className="brand"><a className="mark" href="/launchpad.html" title="About HealthCheckup">Hc</a><div><h1>HealthCheckup</h1><p>Scan what you swallow. See what it does to your medicines.</p></div></div>
        <nav>
          {TABS.map((t) => <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>{t}{t === "My medicines" && status ? ` (${status.meds.length})` : ""}</button>)}
        </nav>
      </header>
      <div className="gold-rule" />
      <div className="shell">
        {error && <div className="banner danger">The API is not reachable: {error}. Start it with venv/bin/uvicorn api:app --port 8000.</div>}
        {status && tab === "Scan" && <ScanTab status={status} setMeds={setMeds} onTarget={openTarget} />}
        {status && tab === "Protein design" && <DesignTab target={target} setTarget={setTarget} drug={drug} setDrug={setDrug} />}
        {status && tab === "My medicines" && <MedsTab status={status} setMeds={setMeds} />}
        {status && tab === "Watchlist" && <WatchTab />}
        {status && tab === "Near me" && <LocalTab status={status} />}
        {status && tab === "Ask Claude" && <ChatTab status={status} />}
      </div>
      <footer>Information from public sources, not medical advice. Confirm with a pharmacist before changing how you take a medicine.</footer>
    </>
  );
}

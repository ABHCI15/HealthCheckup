// Food on the left, proteins in the middle, medicines on the right.
// Gold links mark the protein where a food and a medicine meet; grey links are the medicine's other proteins.
const W = 920;
const NODE_W = { food: 210, protein: 150, drug: 190 };
const X = { food: 20, protein: 385, drug: 710 };
const ROW = 64;

const viaLabel = (via) => ({ absorption: "Absorption in the gut", label: "FDA label warning", potassium: "Potassium level" })[via] || via;

export function buildGraph(report) {
  const foods = new Map();
  const proteins = new Map();
  const drugs = new Map();
  const links = [];
  for (const i of report.interactions) {
    foods.set(i.food, { id: `f:${i.food}`, label: i.food, sub: i.component });
    proteins.set(i.via, { id: `p:${i.via}`, label: viaLabel(i.via), hot: true });
    drugs.set(i.drug, { id: `d:${i.drug}`, label: i.drug });
    links.push({ from: `f:${i.food}`, to: `p:${i.via}`, label: i.food_action, hot: true });
    links.push({ from: `p:${i.via}`, to: `d:${i.drug}`, label: i.drug_relation, hot: true });
  }
  for (const profile of report.drugs) {
    if (!profile.name) continue;
    drugs.set(profile.name, { id: `d:${profile.name}`, label: profile.name });
    let extra = 0;
    for (const link of profile.links) {
      const symbol = link.protein.symbol;
      const hotPair = report.interactions.some((i) => i.drug === profile.name && i.via === symbol);
      if (hotPair) continue;
      if (!proteins.has(symbol)) {
        if (extra >= 4) continue;
        proteins.set(symbol, { id: `p:${symbol}`, label: symbol, hot: false });
      }
      extra++;
      const label = link.relation === "target" && link.action ? link.action.toLowerCase() : link.relation;
      links.push({ from: `p:${symbol}`, to: `d:${profile.name}`, label, hot: false });
    }
  }
  const hotFirst = [...proteins.values()].sort((a, b) => Number(b.hot) - Number(a.hot));
  return { foods: [...foods.values()], proteins: hotFirst, drugs: [...drugs.values()], links };
}

export default function Graph({ report }) {
  const g = buildGraph(report);
  const rows = Math.max(g.foods.length, g.proteins.length, g.drugs.length, 1);
  const H = rows * ROW + 56;
  const pos = {};
  const place = (nodes, kind) => {
    const offset = (H - 40 - nodes.length * ROW) / 2 + 40;
    nodes.forEach((n, i) => {
      pos[n.id] = { x: X[kind], y: offset + i * ROW + 8, w: NODE_W[kind], kind, ...n };
    });
  };
  place(g.foods, "food");
  place(g.proteins, "protein");
  place(g.drugs, "drug");

  const path = (a, b) => {
    const x1 = a.x + a.w, y1 = a.y + 24, x2 = b.x, y2 = b.y + 24, mid = (x1 + x2) / 2;
    // Proteins are evenly spaced, so a label anchored next to its protein never collides with another.
    const atProtein = a.kind === "protein" ? { lx: x1 + 10, ly: y1 - 6, anchor: "start" } : { lx: x2 - 10, ly: y2 - 6, anchor: "end" };
    return { d: `M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`, ...atProtein };
  };

  return (
    <svg className="graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="How each food and medicine act on the same proteins" data-testid="graph">
      <text x={X.food} y="20" className="graph-col">FOOD</text>
      <text x={X.protein} y="20" className="graph-col">PROTEIN</text>
      <text x={X.drug} y="20" className="graph-col">MEDICINE</text>
      {g.links.map((l, i) => {
        const a = pos[l.from], b = pos[l.to];
        if (!a || !b) return null;
        const p = path(a, b);
        return (
          <g key={i} className={l.hot ? "link hot" : "link"}>
            <path d={p.d} />
            {l.hot && <path d={p.d} className="flow" />}
            <text x={p.lx} y={p.ly} textAnchor={p.anchor}>{l.label}</text>
          </g>
        );
      })}
      {Object.values(pos).map((n) => (
        <g key={n.id} className={`node ${n.kind}${n.hot ? " hot" : ""}`} transform={`translate(${n.x},${n.y})`}>
          <rect width={n.w} height="48" rx={n.kind === "protein" ? 24 : 12} />
          <text x={n.w / 2} y={n.sub ? 21 : 30} textAnchor="middle" className="node-label">{n.label.length > 24 ? n.label.slice(0, 23) + "…" : n.label}</text>
          {n.sub && <text x={n.w / 2} y="38" textAnchor="middle" className="node-sub">{n.sub}</text>}
        </g>
      ))}
    </svg>
  );
}

async function request(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* body was not JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  status: () => request("/api/status"),
  scan: (q) => request(`/api/scan?q=${encodeURIComponent(q)}`),
  setMeds: (meds) => request("/api/meds", json("PUT", { meds })),
  drug: (name) => request(`/api/drug/${encodeURIComponent(name)}`),
  local: (state) => request(`/api/local/${state}`),
  watchlist: () => request("/api/watchlist"),
  save: (product) => request("/api/watchlist", json("POST", { product })),
  remove: (key) => request(`/api/watchlist/${encodeURIComponent(key)}`, { method: "DELETE" }),
  runWatch: () => request("/api/watch/run", { method: "POST" }),
  async decode(file) {
    const res = await fetch("/api/decode", { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || "The photo could not be read.");
    return body;
  },
  targets: () => request("/api/targets"),
  binding: (drug, symbol) => request(`/api/binding?drug=${encodeURIComponent(drug)}&symbol=${encodeURIComponent(symbol)}`),
  structure: (symbol) => request(`/api/structure/${encodeURIComponent(symbol)}`),
  chat: (messages) => request("/api/chat", json("POST", { messages })),
  async explain(payload, onText) {
    const res = await fetch("/api/explain", json("POST", payload));
    if (!res.ok) throw new Error("Claude is not available.");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let text = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      text += decoder.decode(value, { stream: true });
      onText(text);
    }
  },
};

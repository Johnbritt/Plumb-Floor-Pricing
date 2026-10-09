"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f2 = (v) => (v == null ? "-" : Number(v).toFixed(2));
const f3 = (v) => (v == null ? "-" : Number(v).toFixed(3));
const usd = (v) => "$" + Math.round(v).toLocaleString("en-US");
const pc = (v, d = 0) => (v == null ? "-" : (v * 100).toFixed(d) + "%");
const sgn = (v) => (v >= 0 ? "+" : "") + v;
const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
const S = { meta: null, asOf: null, q: null, filter: "all", sort: "gain", sel: null, detail: null };

let toastT;
function toast(msg, bad) {
  const t = $("toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, bad ? 6000 : 3000);
}
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let m = r.statusText; try { const j = await r.json(); m = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (e) { /* keep */ }
    throw new Error(m);
  }
  return r.json();
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

/* tabs */
const TABS = ["desk", "log", "data", "method"];
function showTab(t, push = true) {
  if (!TABS.includes(t)) t = "desk";
  TABS.forEach((k) => { $("p-" + k).hidden = k !== t; $("tab-" + k).setAttribute("aria-selected", String(k === t)); });
  if (push) history.replaceState(null, "", "#" + t);
  if (t === "log") renderLog(); if (t === "data") renderData(); if (t === "method") renderMethod();
  window.scrollTo(0, 0);
}
TABS.forEach((k) => $("tab-" + k).addEventListener("click", () => showTab(k)));

/* ---------- floor desk ---------- */
async function loadMeta() {
  S.meta = await api("/api/meta");
  $("who").textContent = S.meta.actor + (S.meta.auth ? "" : " (open access)");
  if (!S.asOf || !S.meta.dates.some((d) => d.date === S.asOf)) S.asOf = S.meta.default_as_of;
}
async function loadQueue(keepSel) {
  if (!S.meta.dates.length) { S.q = null; renderDesk(); return; }
  S.q = await api("/api/queue?as_of=" + S.asOf);
  if (!keepSel || !S.q.cells.some((c) => c.cell_id === S.sel)) {
    const first = sorted(filtered())[0]; S.sel = first ? first.cell_id : null;
  }
  renderDesk();
  if (S.sel) loadDetail(S.sel);
}
function filtered() {
  const cs = S.q.cells;
  return cs.filter((c) => S.filter === "all" || (S.filter === "call" && !c.refused) || (S.filter === "hold" && c.refused) ||
    (S.filter === "notes" && c.notes.length) || (S.filter === "open" && !c.decision));
}
function sorted(cs) {
  const k = { gain: (c) => -Math.abs(c.gain_day), req: (c) => -c.req, cell: (c) => c.cell_id, move: (c) => -Math.abs(c.change) }[S.sort];
  return cs.slice().sort((a, b) => { const x = k(a), y = k(b); return x < y ? -1 : x > y ? 1 : 0; });
}
function callPill(c) {
  if (c.refused) return `<span class="pill hold">Hold</span>`;
  return `<span class="pill rec">${c.rec < c.cur ? "▼" : "▲"} ${f2(c.rec)} (${sgn((c.change * 100).toFixed(0))}%)</span>`;
}
function renderDesk() {
  const el = $("p-desk");
  if (!S.q) {
    el.innerHTML = `<div class="head"><h2>Floor desk</h2></div><div class="card"><p>No data yet. Load the demo data or upload your own on the <a href="#data" id="goData">Data tab</a>.</p></div>`;
    $("goData").addEventListener("click", (e) => { e.preventDefault(); showTab("data"); }); return;
  }
  const q = S.q, sm = q.summary, cs = q.cells;
  const cnt = { all: cs.length, call: sm.calls, hold: sm.holds, notes: sm.with_notes, open: cs.filter((c) => !c.decision).length };
  const chip = (k, t) => `<button class="chip" type="button" data-f="${k}" aria-pressed="${S.filter === k}">${t}<i>${cnt[k]}</i></button>`;
  const opts = S.meta.dates.slice().reverse().map((d) => `<option value="${d.date}" ${d.date === S.asOf ? "selected" : ""}>${d.date}${d.notes ? " · " + d.notes + " notes" : ""}</option>`).join("");
  const rows = sorted(filtered()).map((c) => `<tr class="row" data-id="${esc(c.cell_id)}" aria-selected="${c.cell_id === S.sel}">
    <td><b>${esc(c.cell_id)}</b><small>${c.req.toLocaleString("en-US")} req · ${c.tier}${c.notes.length ? " · " + c.notes.length + " note" + (c.notes.length > 1 ? "s" : "") : ""}</small></td>
    <td class="r num">${f2(c.cur)}</td><td>${callPill(c)}</td>
    <td class="r num">${c.refused ? "-" : usd(c.gain_day)}</td>
    <td>${c.decision ? `<span class="pill done">${{ accept: "Accepted", hold: "Held", custom: "Own" }[c.decision.action]} ${f2(c.decision.final)}</span>` : `<span class="muted">Open</span>`}</td></tr>`).join("");
  el.innerHTML = `
  <div class="head"><h2>Floor desk</h2><p><b>${sm.calls}</b> calls and <b>${sm.holds}</b> holds for <b>${esc(q.target_date)}</b>, based on data through ${esc(q.as_of)}. <b>${sm.decided}</b> of ${sm.total} decided. Estimated gain from the calls: <b class="num">${usd(sm.est_gain_day)}</b> a day.</p></div>
  <div class="bar"><label class="label" for="asof">Data through</label><select id="asof">${opts}</select>
    <button class="btn primary" id="acceptAll" type="button">Accept all open calls</button>
    <a class="btn dark" id="exportFloors" href="/api/export/floors?as_of=${esc(q.as_of)}">Export floor sheet</a>
    <button class="btn" id="resetDay" type="button">Reset this day</button></div>
  <div class="bar">${chip("all", "All cells")}${chip("call", "Calls")}${chip("hold", "Holds")}${chip("notes", "Has notes")}${chip("open", "Open")}
    <span style="flex:1"></span><label class="label" for="sortsel">Sort</label><select id="sortsel"><option value="gain">Est. gain</option><option value="move">Size of move</option><option value="req">Traffic</option><option value="cell">Cell</option></select></div>
  <div class="layout">
    <div class="qwrap"><table aria-label="Cells"><thead><tr><th>Cell</th><th class="r">Floor now</th><th>PLUMB call</th><th class="r">Est. gain / day</th><th>Status</th></tr></thead><tbody>${rows || `<tr><td colspan="5" class="muted">Nothing matches this filter.</td></tr>`}</tbody></table></div>
    <div class="detail" id="detail"><div class="card muted">Select a cell.</div></div>
  </div>`;
  $("sortsel").value = S.sort;
  $("asof").addEventListener("change", (e) => { S.asOf = e.target.value; S.sel = null; loadQueue(); });
  $("sortsel").addEventListener("change", (e) => { S.sort = e.target.value; renderDesk(); if (S.sel) renderDetail(); });
  el.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { S.filter = b.dataset.f; renderDesk(); if (S.sel) renderDetail(); }));
  el.querySelectorAll("tr.row").forEach((r) => r.addEventListener("click", () => { S.sel = r.dataset.id; el.querySelectorAll("tr.row").forEach((x) => x.setAttribute("aria-selected", String(x === r))); loadDetail(S.sel); }));
  $("acceptAll").addEventListener("click", async () => {
    try { const r = await post("/api/decisions/accept_all", { as_of: S.asOf }); toast(`Accepted ${r.accepted} calls, held ${r.held} refused cells.`); await loadQueue(true); } catch (e) { toast(e.message, true); }
  });
  $("resetDay").addEventListener("click", async (ev) => {
    const b = ev.currentTarget;
    if (!b.dataset.arm) { b.dataset.arm = "1"; b.textContent = "Click again to clear decisions"; setTimeout(() => { b.dataset.arm = ""; b.textContent = "Reset this day"; }, 4000); return; }
    try { await post("/api/decisions/reset", { as_of: S.asOf }); toast("Decisions for this day cleared."); await loadQueue(true); } catch (e) { toast(e.message, true); }
  });
}
async function loadDetail(id) {
  try { S.detail = await api(`/api/cells/${encodeURIComponent(id)}?as_of=${S.asOf}`); } catch (e) { toast(e.message, true); return; }
  if (S.sel === id) renderDetail();
}
function chart(c) {
  const h = c.history.slice(-21), cur = c.cur, W = window.innerWidth < 700 ? 340 : 500, H = 280, m = { l: 44, r: 14, t: 34, b: 38 };
  const xs = h.map((r) => Math.log(r.floor / cur));
  let lo = Math.min(-0.3, ...xs) - 0.05, hi = Math.max(0.3, ...xs) + 0.05;
  const fit = c.beta ? (x) => c.beta[0] + c.beta[1] * x + c.beta[2] * x * x : null;
  const ys = h.map((r) => r.rpm); const xsamp = []; for (let i = 0; i <= 60; i++) xsamp.push(lo + ((hi - lo) * i) / 60);
  if (fit) xsamp.forEach((x) => { const v = fit(x); if (v > 0 && v < Math.max(...ys) * 2) ys.push(v); });
  let y0 = Math.max(0, Math.min(...ys) * 0.9), y1 = Math.max(...ys) * 1.08;
  const X = lin(lo, hi, m.l, W - m.r), Y = lin(y0, y1, H - m.b, m.t); let g = "";
  for (let i = 0; i <= 3; i++) { const v = y0 + ((y1 - y0) * i) / 3; g += `<line class="grid" x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/><text x="${m.l - 6}" y="${Y(v) + 4}" text-anchor="end">${v.toFixed(2)}</text>`; }
  g += `<line class="axis" x1="${m.l}" x2="${W - m.r}" y1="${H - m.b}" y2="${H - m.b}"/>`;
  [-0.4, -0.2, 0, 0.2, 0.4].filter((t) => t > lo && t < hi).forEach((t) => { g += `<line class="axis" x1="${X(t)}" x2="${X(t)}" y1="${H - m.b}" y2="${H - m.b + 4}"/><text x="${X(t)}" y="${H - m.b + 16}" text-anchor="middle">${f2(cur * Math.exp(t))}</text>`; });
  if (fit) { const pts = xsamp.map((x) => [X(x), Y(Math.min(y1, Math.max(y0, fit(x))))]); g += `<path d="M${pts.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" L")}" fill="none" stroke="var(--accent)" stroke-width="2.6"/>`; }
  g += `<line x1="${X(0)}" x2="${X(0)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--ink)" stroke-width="1.6"/><text x="${X(0) + 5}" y="${m.t - 6}">now ${f2(cur)}</text>`;
  if (c.rec && !c.refused) { const xr = Math.log(c.rec / cur); g += `<line x1="${X(xr)}" x2="${X(xr)}" y1="${m.t}" y2="${H - m.b}" stroke="var(--accent-ink)" stroke-width="1.6" stroke-dasharray="5 4"/><text x="${X(xr) + (xr < 0 ? -5 : 5)}" y="${m.t + 10}" text-anchor="${xr < 0 ? "end" : "start"}" style="fill:var(--accent-ink)">call ${f2(c.rec)}</text>`; }
  h.forEach((r, i) => { g += `<circle cx="${X(xs[i]).toFixed(1)}" cy="${Y(r.rpm).toFixed(1)}" r="4" fill="var(--ink)" opacity="${(0.35 + 0.65 * (i + 1) / h.length).toFixed(2)}"/>`; });
  g += `<text x="${(m.l + W - m.r) / 2}" y="${H - 3}" text-anchor="middle">floor, CPM (log scale)</text><text x="${m.l}" y="12">$ per 1,000 requests, last ${h.length} days</text>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Last ${h.length} days of floor against revenue with the fitted curve">${g}</svg>`;
}
function renderDetail() {
  const c = S.detail, el = $("detail"); if (!c || !el) return;
  const pr = S.meta.params, held = c.refused;
  const conf = c.z == null ? 0 : Math.min(Math.max(c.z / pr.zfull, 0), 1) * (c.concave ? 1 : pr.nc_scale);
  const band = c.gain_1k == null ? "-" : `${sgn(f3(c.gain_1k - 1.645 * c.se))} to ${sgn(f3(c.gain_1k + 1.645 * c.se))}`.replace("+-", "-").replace("+ ", "+");
  const used = (c.plan && c.plan.evidence || []).map((e) => e[1]);
  const notes = c.notes.length ? c.notes.map((n) => `<div class="note ${used.includes(n.text) ? "used" : ""}">${esc(n.text)}<small>${esc(n.date)}${n.age === 0 ? ", today" : ", " + n.age + " day" + (n.age > 1 ? "s" : "") + " ago"}</small></div>`).join("") : `<p class="muted">No ops notes in the last three days.</p>`;
  const plan = c.plan && c.plan.evidence.length ? `<ul class="plain" style="font-size:14px">${c.plan.evidence.map((e) => `<li><b>${esc(e[0])}</b></li>`).join("")}</ul>` : "";
  const d = c.decision;
  el.innerHTML = `
  <div class="card" style="display:flex;flex-direction:column;gap:12px">
    <div><h3 style="font-size:22px;letter-spacing:-.02em">${esc(c.cell_id)}</h3><p class="muted num" style="font-size:13px">${c.tier} traffic · ${c.req.toLocaleString("en-US")} req / day · ${c.n_days} days of history</p></div>
    ${chart(c)}
    <div class="callbox ${held ? "hold" : ""}">
      <span class="label">PLUMB call for ${esc(S.q.target_date)}</span>
      ${held ? `<h3>Hold at ${f2(c.cur)}</h3><p>${esc(c.reason)}</p>` : `<h3>${c.rec === c.cur ? "Keep" : "Move to"} ${f2(c.rec)} (${sgn((c.change * 100).toFixed(0))}%)</h3>`}
      <div class="kv"><span>Floor now</span><span>${f2(c.cur)}</span>
        ${c.gain_1k == null ? "" : `<span>Predicted gain at the fitted optimum</span><span>${sgn(f3(c.gain_1k))} per 1k requests</span><span>90% band</span><span>${band}</span><span>Confidence in the move</span><span>${pc(conf)} of the fitted step</span>`}
        <span>Est. gain at the applied floor</span><span>${held ? "-" : usd(c.gain_day) + " / day"}</span></div>
      ${plan}
    </div>
    <div><span class="label">What ops wrote, last three days</span><div class="notes" style="margin-top:6px">${notes}</div></div>
    <div class="decide"><span class="label">Your decision</span>
      ${d ? `<p><span class="pill done">${{ accept: "Accepted", hold: "Held", custom: "Own floor" }[d.action]} ${f2(d.final)}</span> <span class="muted" style="font-size:13px">by ${esc(d.actor)}${d.comment ? ". " + esc(d.comment) : ""}</span></p>` : ""}
      <div class="row2"><button class="btn primary small" id="bAcc" type="button" ${held ? "disabled" : ""}>Accept ${held ? "" : f2(c.rec)}</button><button class="btn small" id="bHold" type="button">Hold at ${f2(c.cur)}</button></div>
      <div class="row2"><label class="label" for="own">Your floor</label><input id="own" type="number" step="0.01" min="0.01" inputmode="decimal" value="${f2(held ? c.cur : c.rec)}" style="width:96px"><button class="btn small dark" id="bOwn" type="button">Set my floor</button></div>
      <textarea id="why" rows="2" maxlength="500" placeholder="Reason (required when you set your own floor)" aria-label="Reason"></textarea>
    </div>
  </div>`;
  const send = async (action, floor) => {
    try { await post("/api/decisions", { cell_id: c.cell_id, as_of: S.asOf, action, floor, comment: $("why").value }); toast(`Saved: ${c.cell_id}.`); await loadQueue(true); } catch (e) { toast(e.message, true); }
  };
  $("bAcc").addEventListener("click", () => send("accept"));
  $("bHold").addEventListener("click", () => send("hold"));
  $("bOwn").addEventListener("click", () => { const v = parseFloat($("own").value); if (!(v > 0)) { toast("Enter a floor above zero.", true); return; } send("custom", v); });
}

/* ---------- decisions log ---------- */
async function renderLog() {
  const el = $("p-log"); let d;
  try { d = await api("/api/decisions?limit=300"); } catch (e) { el.innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
  const n = d.counts, lab = { accept: "Accepted", hold: "Held", custom: "Own floor" };
  const rows = d.rows.map((r) => `<tr><td class="num">${esc(r.ts.replace("T", " ").replace("+00:00", " UTC"))}</td><td>${esc(r.actor)}</td><td>${esc(r.as_of)}</td><td><b>${esc(r.cell_id)}</b></td><td>${lab[r.action]}</td>
    <td class="r num">${f2(r.current_floor)}</td><td class="r num">${r.refused ? "held" : f2(r.rec_floor)}</td><td class="r num">${f2(r.final_floor)}</td><td style="white-space:normal;min-width:200px">${esc(r.comment || "")}</td></tr>`).join("");
  el.innerHTML = `<div class="head"><h2>Decisions</h2><p>Every accept, hold and override, with who made it and why. This is the audit trail, and the override rate is what a pilot reads.</p></div>
  <div class="card stats"><div class="stat"><span class="label">Decisions</span><b>${d.total}</b></div><div class="stat"><span class="label">Accepted</span><b>${n.accept || 0}</b></div><div class="stat"><span class="label">Held</span><b>${n.hold || 0}</b></div><div class="stat"><span class="label">Own floor</span><b>${n.custom || 0}</b></div><div class="stat"><span class="label">Override rate</span><b>${d.override_rate == null ? "-" : pc(d.override_rate, 1)}</b></div></div>
  <div class="bar"><a class="btn dark" href="/api/export/decisions">Export decisions CSV</a></div>
  <div class="qwrap tbl-scroll"><table aria-label="Decision log"><thead><tr><th>Time</th><th>By</th><th>Data through</th><th>Cell</th><th>Action</th><th class="r">Floor now</th><th class="r">PLUMB call</th><th class="r">Final</th><th>Reason</th></tr></thead><tbody>${rows || `<tr><td colspan="9" class="muted">No decisions yet. Make one on the Floor desk.</td></tr>`}</tbody></table></div>`;
}

/* ---------- data ---------- */
async function renderData() {
  await loadMeta(); const m = S.meta, el = $("p-data");
  el.innerHTML = `<div class="head"><h2>Data</h2><p>PLUMB reads one daily row per cell and an optional free-text ops note. Upload new days as they arrive and the desk moves forward.</p></div>
  <div class="card stats"><div class="stat"><span class="label">Cells</span><b>${m.cells}</b></div><div class="stat"><span class="label">Daily rows</span><b>${m.rows.toLocaleString("en-US")}</b></div><div class="stat"><span class="label">Ops notes</span><b>${m.notes.toLocaleString("en-US")}</b></div><div class="stat"><span class="label">First day</span><b style="font-size:18px">${m.first || "-"}</b></div><div class="stat"><span class="label">Last day</span><b style="font-size:18px">${m.last || "-"}</b></div></div>
  <div class="grid2">
    <section class="drop"><h3>Daily performance</h3><p class="muted" style="font-size:14px">CSV with <span class="num">cell_id, date, requests, floor_cpm</span> and either <span class="num">revenue_per_1k_requests</span> or <span class="num">revenue_usd</span>. Existing days are replaced. A cell needs ${m.min_history} days before it gets a call.</p>
      <div class="row2"><input type="file" id="fDaily" accept=".csv,text/csv" aria-label="Daily CSV"><button class="btn primary small" id="uDaily" type="button">Upload</button><a href="/api/templates/daily" class="btn small">Template</a></div><p class="err" id="eDaily"></p></section>
    <section class="drop"><h3>Ops notes</h3><p class="muted" style="font-size:14px">CSV with <span class="num">cell_id, date, text</span>. Free text, as ops write it. Duplicates are ignored.</p>
      <div class="row2"><input type="file" id="fNotes" accept=".csv,text/csv" aria-label="Notes CSV"><button class="btn primary small" id="uNotes" type="button">Upload</button><a href="/api/templates/notes" class="btn small">Template</a></div><p class="err" id="eNotes"></p></section>
  </div>
  <section class="card" style="display:flex;flex-direction:column;gap:10px"><h3>Demo data</h3><p class="muted">The synthetic dataset from the case study: 40 cells, 180 days, with outages, surges, reporting glitches and notes. No real data.</p>
    <div class="row2"><button class="btn small" id="seed" type="button">Load demo data</button><button class="btn small danger" id="clear" type="button">Delete all data and decisions</button></div></section>`;
  const up = (btn, input, path, errEl) => $(btn).addEventListener("click", async () => {
    const f = $(input).files[0]; $(errEl).textContent = ""; if (!f) { $(errEl).textContent = "Choose a CSV file first."; return; }
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api(path, { method: "POST", body: fd }); toast(r.loaded != null ? `Loaded ${r.loaded.toLocaleString("en-US")} rows${r.skipped ? ", skipped " + r.skipped : ""}.` : `Added ${r.added} notes.`); await loadMeta(); renderData(); S.q = null; } catch (e) { $(errEl).textContent = e.message; }
  });
  up("uDaily", "fDaily", "/api/upload/daily", "eDaily"); up("uNotes", "fNotes", "/api/upload/notes", "eNotes");
  $("seed").addEventListener("click", async () => { try { const r = await api("/api/seed", { method: "POST" }); toast(`Demo data loaded: ${r.daily_rows.toLocaleString("en-US")} rows.`); await loadMeta(); renderData(); S.q = null; } catch (e) { toast(e.message, true); } });
  $("clear").addEventListener("click", async (ev) => {
    const b = ev.currentTarget; if (!b.dataset.arm) { b.dataset.arm = "1"; b.textContent = "Click again to delete everything"; setTimeout(() => { b.dataset.arm = ""; b.textContent = "Delete all data and decisions"; }, 4000); return; }
    try { await api("/api/data/clear?confirm=yes", { method: "POST" }); toast("All data deleted."); await loadMeta(); renderData(); S.q = null; } catch (e) { toast(e.message, true); }
  });
}

/* ---------- method ---------- */
function renderMethod() {
  const m = S.meta, p = m.params, el = $("p-method");
  el.innerHTML = `<div class="head"><h2>Method</h2><p>How a floor gets set, in the order it happens.</p></div>
  <div class="grid2">
    <section class="card"><span class="label">1</span><h3>Statistics, no model</h3><p class="muted">Fits revenue per 1,000 requests against log floor over the last ${m.window_days} days. Returns a proposed floor, a predicted gain and an uncertainty band. The step is capped at 25% a day and shrunk by confidence.</p></section>
    <section class="card"><span class="label">2</span><h3>Agent, judgment only</h3><p class="muted">Reads the ops notes and returns a trust plan: hold on an outage, drop a lagged reporting day, allow only a raise before a surge, ignore a benign alert. It never writes a price. Backend now: <b>${m.agent === "claude" ? "Claude" : "offline keyword rules"}</b>.</p></section>
    <section class="card"><span class="label">3</span><h3>The person decides</h3><p class="muted">Accept, hold, or set your own floor with a reason. Refusals come back with the reason attached. Everything is logged on the Decisions tab.</p></section>
  </div>
  <section class="card"><h3 style="margin-bottom:8px">Hard refusals and parameters</h3>
    <ul class="plain"><li>Fewer than ${m.min_history} days of history, or too little floor variation to identify a curve.</li><li>Traffic below ${p.thinV.toLocaleString("en-US")} requests a day (median of the last 14 days).</li><li>The last day is an outlier against the fitted curve (more than ${p.rz} residual standard deviations).</li></ul>
    <pre class="code">${esc(JSON.stringify(p))}</pre><p class="muted" style="font-size:13px;margin-top:6px">Tuned on a synthetic world and frozen. Override with the PLUMB_PARAMS environment variable.</p></section>
  <div class="callout"><span class="mark"></span><div><b>Read this before trusting a number.</b> The results behind these defaults come from a simulator. Simulated bidders do not react to floors, and the manual-pricing baseline is a model, not a measurement. Run the pilot in the repository (40 cells, a shadow week, matched control) before relying on the estimated gains.</div></div>`;
}

/* ---------- boot ---------- */
(async function () {
  try { await loadMeta(); await loadQueue(); } catch (e) { $("p-desk").innerHTML = `<p class="err">${esc(e.message)}</p>`; }
  const h = (location.hash || "").slice(1); if (TABS.includes(h)) showTab(h, false);
  window.addEventListener("hashchange", () => { const k = location.hash.slice(1); if (TABS.includes(k)) showTab(k, false); });
})();

"use strict";

// ===========================================================================
// SCOUT — static venture-intelligence dashboard.
// Reads precomputed data.json (from `python -m scout export`) and renders a
// filterable / sortable / searchable investor view with a watchlist + drawer.
// ===========================================================================

const state = {
  data: null,
  companies: [],
  filtered: [],
  view: "grid",
  tab: "feed",
  watch: new Set(JSON.parse(localStorage.getItem("scout:watch") || "[]")),
  filters: { aiOnly: true, category: "", stage: "", minScore: 0, sort: "score", query: "", _dateFloor: null },
};

const $ = (id) => document.getElementById(id);
const fmtPct = (x) => `${Math.round((x || 0) * 100)}%`;
const escapeHtml = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const monthLabel = (ym) => {
  if (!ym || ym === "unknown") return "Unknown date";
  const [y, m] = ym.split("-");
  return `${MONTH_NAMES[parseInt(m, 10) - 1] || "?"} ${y}`;
};

const VERDICT_CLASS = {
  "Strong interest": "v-strong", "Track closely": "v-track",
  "Monitor": "v-monitor", "Pass for now": "v-pass",
};

const raisedOf = (c) => {
  const r = c.raw || {};
  return r.amount_sold || r.offering_amount || 0;
};
const stageOf = (c) => (c.raw && c.raw.stage) || (c.memo && c.memo.estimated_stage) || "";
const fmtMoney = (n) => {
  if (!n) return "";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}K`;
  return `$${n}`;
};

// --- Boot ------------------------------------------------------------------
async function load() {
  startClock();
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    state.data = await res.json();
  } catch (e) {
    $("groups").innerHTML = `<div class="empty">Could not load data.json. Run <code>python -m scout run --source sample --research --export</code>.</div>`;
    return;
  }
  state.companies = state.data.companies || [];
  initControls();
  initTabs();
  renderStats();
  renderTrends();
  updateWatchCount();
  apply();
}

function startClock() {
  const tick = () => {
    const d = new Date();
    $("clock").textContent = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  tick();
  setInterval(tick, 30000);
}

// --- Stats -----------------------------------------------------------------
function renderStats() {
  const s = state.data.stats || {};
  const ai = state.companies.filter((c) => c.is_ai);
  const verified = state.companies.filter((c) => c.verified_real).length;
  const capital = ai.reduce((a, c) => a + raisedOf(c), 0);
  const catCount = {};
  ai.forEach((c) => { if (c.ai_category) catCount[c.ai_category] = (catCount[c.ai_category] || 0) + 1; });
  const hottest = Object.entries(catCount).sort((a, b) => b[1] - a[1])[0];

  const cards = [
    { num: s.total ?? state.companies.length, lbl: "Discovered" },
    { num: ai.length, lbl: "AI-related", accent: true },
    { num: verified, lbl: "SEC-verified" },
    { num: fmtMoney(capital) || "—", lbl: "Capital tracked", serif: true },
    { num: hottest ? hottest[0] : "—", lbl: "Hottest category", serif: true },
  ];
  $("stats").innerHTML = cards.map((c) =>
    `<div class="stat"><div class="lbl">${escapeHtml(c.lbl)}</div>
     <div class="num ${c.accent ? "accent" : ""} ${c.serif ? "serif-sm" : ""}">${escapeHtml(c.num)}</div></div>`
  ).join("");
}

// --- Tabs ------------------------------------------------------------------
function initTabs() {
  document.querySelectorAll(".tab").forEach((t) =>
    t.addEventListener("click", () => switchTab(t.getAttribute("data-tab")))
  );
}
function switchTab(name) {
  state.tab = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.getAttribute("data-tab") === name));
  ["feed", "trends", "watch"].forEach((n) => { $("panel-" + n).hidden = n !== name; });
  if (name === "watch") renderWatchlist();
}

// --- Trends ----------------------------------------------------------------
function renderTrends() {
  const t = state.data.trends || {};
  const months = t.ai_by_month || [];
  const max = Math.max(1, ...months.map((m) => m.count));
  $("monthBars").innerHTML = months.map((m) => {
    const h = Math.round((m.count / max) * 100);
    return `<div class="bar-col"><div class="bar" style="height:${h}%" data-count="${m.count}"></div><div class="bar-label">${monthLabel(m.month).split(" ")[0]}</div></div>`;
  }).join("") || '<div class="mom-empty">No data</div>';

  const cats = t.categories || [];
  const catMax = Math.max(1, ...cats.map((c) => c.count));
  $("catList").innerHTML = cats.slice(0, 6).map((c) =>
    `<div class="catrow"><span class="nm">${escapeHtml(c.category)}</span><span class="ct">${c.count}</span><div class="track"><div class="fill" style="width:${(c.count / catMax) * 100}%"></div></div></div>`
  ).join("") || '<div class="mom-empty">No data</div>';

  const up = (t.accelerating || []).map((r) => `<div class="mom-row"><span class="pill up">▲ +${r.delta}</span><span>${escapeHtml(r.category)}</span></div>`);
  const down = (t.cooling || []).map((r) => `<div class="mom-row"><span class="pill down">▼ ${r.delta}</span><span>${escapeHtml(r.category)}</span></div>`);
  const mom = [...up, ...down];
  $("momentum").innerHTML = mom.length ? mom.join("") : '<div class="mom-empty">Need ≥2 months of data to compute momentum.</div>';

  const geo = t.geography || [];
  const geoMax = Math.max(1, ...geo.map((g) => g.count));
  $("geoList").innerHTML = geo.slice(0, 6).map((g) =>
    `<div class="catrow"><span class="nm">${escapeHtml(g.jurisdiction)}</span><span class="ct">${g.count}</span><div class="track"><div class="fill" style="width:${(g.count / geoMax) * 100}%"></div></div></div>`
  ).join("") || '<div class="mom-empty">No data</div>';
}

// --- Controls --------------------------------------------------------------
function initControls() {
  const cats = [...new Set(state.companies.filter((c) => c.ai_category).map((c) => c.ai_category))].sort();
  $("category").innerHTML = `<option value="">All categories</option>` + cats.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");

  const stages = [...new Set(state.companies.map(stageOf).filter(Boolean))];
  const stageOrder = ["Stealth / Pre-seed", "Pre-seed", "Seed", "Series A", "Series B", "Growth"];
  stages.sort((a, b) => stageOrder.indexOf(a) - stageOrder.indexOf(b));
  $("stage").innerHTML = `<option value="">All stages</option>` + stages.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join("");

  $("aiOnly").addEventListener("change", (e) => { state.filters.aiOnly = e.target.checked; apply(); });
  $("category").addEventListener("change", (e) => { state.filters.category = e.target.value; apply(); });
  $("stage").addEventListener("change", (e) => { state.filters.stage = e.target.value; apply(); });
  $("sort").addEventListener("change", (e) => { state.filters.sort = e.target.value; apply(); });
  $("minScore").addEventListener("input", (e) => {
    state.filters.minScore = e.target.value / 100;
    $("minScoreLabel").textContent = `${e.target.value}%`;
    apply();
  });
  $("search").addEventListener("input", debounce((e) => runQuery(e.target.value), 200));
  $("viewGrid").addEventListener("click", () => setView("grid"));
  $("viewList").addEventListener("click", () => setView("list"));

  const examples = ["robotics seed stage", "raised over $5M", "AI security", "formed this month", "high confidence"];
  $("examples").innerHTML = examples.map((q) => `<span class="chip">${escapeHtml(q)}</span>`).join("");
  document.querySelectorAll(".chip").forEach((ch) =>
    ch.addEventListener("click", () => { $("search").value = ch.textContent; runQuery(ch.textContent); })
  );

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== $("search")) { e.preventDefault(); $("search").focus(); }
    if (e.key === "Escape") closeMemo();
  });
}

function setView(v) {
  state.view = v;
  $("viewGrid").classList.toggle("active", v === "grid");
  $("viewList").classList.toggle("active", v === "list");
  render();
}

// --- Natural-language query (stretch goal 7) -------------------------------
function runQuery(text) {
  const q = (text || "").toLowerCase().trim();
  state.filters.query = q;

  const catMap = {
    "infrastructure": "AI Infrastructure", "infra": "AI Infrastructure",
    "developer tool": "Developer Tools", "dev tool": "Developer Tools",
    "agent": "AI Agents", "agentic": "AI Agents", "vision": "Computer Vision",
    "nlp": "NLP / Language", "language": "NLP / Language",
    "robot": "Robotics", "health": "Healthcare AI", "clinical": "Healthcare AI",
    "fintech": "Fintech AI", "finance": "Fintech AI", "security": "AI Security",
    "generative": "Generative Media", "analytics": "Data / Analytics",
  };
  let matchedCat = "";
  for (const [k, v] of Object.entries(catMap)) { if (q.includes(k)) { matchedCat = v; break; } }
  if (matchedCat && [...$("category").options].some((o) => o.value === matchedCat)) {
    $("category").value = matchedCat; state.filters.category = matchedCat;
  }

  // stage intent
  const stageMap = { "pre-seed": "Pre-seed", "preseed": "Pre-seed", "seed": "Seed", "series a": "Series A", "series b": "Series B", "growth": "Growth", "stealth": "Stealth / Pre-seed" };
  for (const [k, v] of Object.entries(stageMap)) {
    if (q.includes(k) && [...$("stage").options].some((o) => o.value === v)) { $("stage").value = v; state.filters.stage = v; break; }
  }

  // capital intent: "raised over $5m" / "over 5m"
  const cap = q.match(/(?:over|above|>\s*)\$?\s*(\d+(?:\.\d+)?)\s*(k|m|b)?/);
  state.filters._minRaised = 0;
  if (cap && (q.includes("rais") || q.includes("$") || q.includes("over") || q.includes("above"))) {
    let v = parseFloat(cap[1]);
    const unit = cap[2];
    v *= unit === "b" ? 1e9 : unit === "k" ? 1e3 : 1e6;
    state.filters._minRaised = v;
  }

  // time window
  state.filters._dateFloor = null;
  const months = state.data.months || [];
  if (q.includes("this month") && months[0]) {
    const d = new Date(); state.filters._dateFloor = `${months[0]}-01`;
  } else {
    const days = q.match(/last\s+(\d+)\s+days?/);
    if (q.includes("last 30 days") || days) {
      const n = days ? parseInt(days[1], 10) : 30;
      const d = new Date(); d.setDate(d.getDate() - n);
      state.filters._dateFloor = d.toISOString().slice(0, 10);
    }
  }

  if (q.includes("high confidence") || q.includes("strong")) {
    $("minScore").value = 75; $("minScoreLabel").textContent = "75%"; state.filters.minScore = 0.75;
  }
  apply();
}

// --- Filter / sort ---------------------------------------------------------
function apply() {
  const f = state.filters;
  let rows = state.companies.slice();

  if (f.aiOnly) rows = rows.filter((c) => c.is_ai);
  if (f.category) rows = rows.filter((c) => c.ai_category === f.category);
  if (f.stage) rows = rows.filter((c) => stageOf(c) === f.stage);
  if (f.minScore > 0) rows = rows.filter((c) => (c.ai_score || 0) >= f.minScore);
  if (f._minRaised) rows = rows.filter((c) => raisedOf(c) >= f._minRaised);
  if (f._dateFloor) rows = rows.filter((c) => (c.formation_date || "") >= f._dateFloor);

  if (f.query) {
    const stop = ["this","month","last","days","companies","company","founded","formed","show","the","with","high","confidence","and","for","over","above","raised","stage","me"];
    const terms = f.query.split(/\s+/).filter((t) => t.length > 2 && !stop.includes(t) && !/^\$?\d/.test(t));
    if (terms.length) {
      rows = rows.filter((c) => {
        const hay = `${c.name} ${c.description} ${c.ai_category} ${stageOf(c)} ${(c.founders||[]).map(x=>x.name).join(" ")} ${(c.ai_signals || []).join(" ")}`.toLowerCase();
        return terms.every((t) => hay.includes(t));
      });
    }
  }

  rows.sort((a, b) => {
    if (f.sort === "name") return a.name.localeCompare(b.name);
    if (f.sort === "date") return (b.formation_date || "").localeCompare(a.formation_date || "");
    if (f.sort === "raised") return raisedOf(b) - raisedOf(a);
    if (f.sort === "conf") return (b.ai_score || 0) - (a.ai_score || 0);
    return ((b.scores && b.scores.overall) || 0) - ((a.scores && a.scores.overall) || 0) || (b.ai_score || 0) - (a.ai_score || 0);
  });

  state.filtered = rows;
  render();
}

function render() {
  const rows = state.filtered;
  $("resultMeta").textContent = `${rows.length} ${rows.length === 1 ? "company" : "companies"} · click any card for the full memo · ★ to save`;
  $("empty").hidden = rows.length !== 0;

  const groups = {}; const order = [];
  for (const c of rows) {
    const m = c.month || "unknown";
    if (!groups[m]) { groups[m] = []; order.push(m); }
    groups[m].push(c);
  }
  order.sort((a, b) => (b === "unknown" ? -1 : a === "unknown" ? 1 : b.localeCompare(a)));

  $("groups").className = "groups" + (state.view === "list" ? " list" : "");
  $("groups").innerHTML = order.map((m) => `
    <div class="month-group">
      <div class="month-head">${monthLabel(m)} <span class="count">${groups[m].length} ${groups[m].length === 1 ? "company" : "companies"}</span></div>
      <div class="cards">${groups[m].map(cardHtml).join("")}</div>
    </div>`).join("");

  bindCards($("groups"));
}

function bindCards(root) {
  root.querySelectorAll("[data-memo]").forEach((b) =>
    b.addEventListener("click", (e) => { if (e.target.closest(".star") || e.target.closest("a")) return; openMemo(b.getAttribute("data-memo")); })
  );
  root.querySelectorAll(".star").forEach((s) =>
    s.addEventListener("click", (e) => { e.stopPropagation(); toggleWatch(s.getAttribute("data-id")); })
  );
}

// --- Card ------------------------------------------------------------------
function verifiedBadge(c) {
  if (!c.verified_real) return "";
  const prov = (c.verification || []).join(" · ");
  const edgarUrl = (c.raw && c.raw.edgar_url) || "";
  const title = `Verified real — ${prov || "authoritative registry"}`;
  return edgarUrl
    ? `<a class="vbadge" href="${escapeHtml(edgarUrl)}" target="_blank" rel="noopener" title="${escapeHtml(title)}">✓ Verified</a>`
    : `<span class="vbadge" title="${escapeHtml(title)}">✓ Verified</span>`;
}

function cardHtml(c) {
  const edgarUrl = (c.raw && c.raw.edgar_url) || (c.raw && c.raw.filing_url) || "";
  const link = c.website && c.website_verified ? c.website : edgarUrl;
  const linkLabel = c.website && c.website_verified
    ? c.website.replace(/^https?:\/\//, "").replace(/\/$/, "")
    : edgarUrl ? "SEC filing ↗" : "";
  const cat = c.ai_category ? `<span class="tag cat">${escapeHtml(c.ai_category)}</span>` : "";
  const rec = c.recommendation;
  const recBadge = rec ? `<span class="verdict ${VERDICT_CLASS[rec.verdict] || ""}">${escapeHtml(rec.verdict)}</span>` : "";
  const opp = c.scores ? `<div class="opp-badge"><div class="v">${c.scores.overall}</div><div class="l">opp</div></div>` : "";
  const stage = stageOf(c);
  const raised = raisedOf(c);
  const meta = [
    stage ? `<span class="pill-meta">${escapeHtml(stage)}</span>` : "",
    raised ? `<span class="pill-meta raised">${fmtMoney(raised)} raised</span>` : "",
    `<span class="pill-meta">conf ${fmtPct(c.ai_score)}</span>`,
  ].join("");
  const realFounders = (c.founders || []).filter((f) => f.source === "sec_filing");
  const fline = realFounders.length
    ? `<div class="founders-line"><span class="fk">Team</span>${escapeHtml(realFounders.slice(0, 3).map((f) => f.name).join(", "))}${realFounders.length > 3 ? ` +${realFounders.length - 3}` : ""}</div>`
    : "";
  const on = state.watch.has(c.id) ? "on" : "";

  return `
    <div class="card" data-memo="${escapeHtml(c.id)}">
      <div class="card-top">
        <div>
          <h3>${escapeHtml(c.name)} ${verifiedBadge(c)}</h3>
          <div class="sub">${escapeHtml(c.jurisdiction || "—")} · formed ${escapeHtml(c.formation_date || "?")}</div>
        </div>
        ${opp}
      </div>
      <div class="metaline">${meta}</div>
      ${c.description ? `<p class="desc">${escapeHtml(c.description)}</p>` : ""}
      ${fline}
      <div class="tags">${cat}${recBadge}</div>
      <div class="card-foot">
        ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(linkLabel)}</a>` : `<span class="sub">no website yet</span>`}
        <div class="foot-actions">
          <button class="star ${on}" data-id="${escapeHtml(c.id)}" title="Save to watchlist">★</button>
          <button class="memo-btn">Analysis →</button>
        </div>
      </div>
    </div>`;
}

// --- Watchlist -------------------------------------------------------------
function toggleWatch(id) {
  if (state.watch.has(id)) state.watch.delete(id); else state.watch.add(id);
  localStorage.setItem("scout:watch", JSON.stringify([...state.watch]));
  updateWatchCount();
  document.querySelectorAll(`.star[data-id="${CSS.escape(id)}"]`).forEach((s) => s.classList.toggle("on", state.watch.has(id)));
  if (state.tab === "watch") renderWatchlist();
}
function updateWatchCount() { $("watchCount").textContent = state.watch.size; }
function renderWatchlist() {
  const rows = state.companies.filter((c) => state.watch.has(c.id));
  $("watchEmpty").hidden = rows.length !== 0;
  $("watchlist").className = "groups" + (state.view === "list" ? " list" : "");
  $("watchlist").innerHTML = rows.length
    ? `<div class="month-group"><div class="cards">${rows.map(cardHtml).join("")}</div></div>`
    : "";
  bindCards($("watchlist"));
}

// --- Drawer ----------------------------------------------------------------
const DIM_LABELS = {
  team_quality: "Team", market_size: "Market size", product_differentiation: "Differentiation",
  technical_complexity: "Technical", defensibility: "Defensibility", timing: "Timing",
};

function scoreBarsHtml(scores) {
  if (!scores || !scores.dimensions) return "";
  const rows = Object.entries(scores.dimensions).map(([k, v]) => `
    <div class="dim">
      <div class="dim-top"><span>${escapeHtml(DIM_LABELS[k] || k)}</span><b>${v.score}</b></div>
      <div class="dim-track"><div class="dim-fill" style="width:${v.score}%"></div></div>
      <div class="dim-reason">${escapeHtml(v.reason || "")}</div>
    </div>`).join("");
  return `<div class="memo-sec"><h4>Opportunity score — ${scores.overall}/100 <span class="badge-gen">confidence ${fmtPct(scores.confidence)}</span></h4><div class="dims">${rows}</div></div>`;
}

function foundersHtml(founders) {
  if (!founders || !founders.length) return "";
  const real = founders.filter((f) => f.source === "sec_filing");
  const list = real.length ? real : founders;
  const items = list.map((f) => {
    const link = f.linkedin || f.profile_url;
    const prev = (f.previous_companies || []).map((p) => `<span class="tag">${escapeHtml(p)}</span>`).join("");
    return `
    <div class="founder">
      <div class="founder-top"><b>${escapeHtml(f.name)}</b><span class="founder-role">${escapeHtml(f.role || "")}</span></div>
      ${f.background ? `<div class="founder-bg">${escapeHtml(f.background)}</div>` : ""}
      <div class="founder-meta">
        ${f.location ? `<span class="founder-loc">${escapeHtml(f.location)}</span>` : ""}
        ${prev}
        ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">in · find on LinkedIn ↗</a>` : ""}
      </div>
    </div>`;
  }).join("");
  const label = real.length ? "named in SEC filing" : (list[0]?.source || "");
  return `<div class="memo-sec"><h4>Founding team <span class="badge-gen">${escapeHtml(label)}</span></h4>${items}</div>`;
}

function competitiveHtml(comp) {
  if (!comp) return "";
  const leaders = (comp.leaders || []).map((l) => `<span class="tag cat">${escapeHtml(l)}</span>`).join("");
  const adj = (comp.adjacent || []).map((a) => `<span class="tag">${escapeHtml(a)}</span>`).join("");
  return `
    <div class="memo-sec">
      <h4>Competitive landscape</h4>
      ${comp.positioning ? `<p>${escapeHtml(comp.positioning)}</p>` : ""}
      <div class="comp-block"><div class="k">Category leaders</div><div class="tags">${leaders || "—"}</div></div>
      <div class="comp-block"><div class="k">Discovered peers</div><div class="tags">${adj || "<span class='founder-loc'>none yet in dataset</span>"}</div></div>
    </div>`;
}

function verificationHtml(c) {
  const prov = c.verification || [];
  const edgarUrl = (c.raw && c.raw.edgar_url) || "";
  const filingUrl = (c.raw && c.raw.filing_url) || edgarUrl;
  if (!prov.length && !filingUrl) return "";
  const items = prov.map((p) => `<li>${escapeHtml(p)}</li>`).join("");
  const status = c.verified_real ? `<span class="vbadge">✓ Verified real</span>` : `<span class="badge-gen">unverified</span>`;
  return `<div class="memo-sec"><h4>Verification ${status}</h4>${items ? `<ul>${items}</ul>` : "<p>No authoritative signal found.</p>"}</div>`;
}

function openMemo(id) {
  const c = state.companies.find((x) => x.id === id);
  if (!c) return;
  const m = c.memo || {};
  const rec = c.recommendation;
  const raw = c.raw || {};
  const risks = (m.risks || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
  const recHtml = rec ? `
    <div class="rec ${VERDICT_CLASS[rec.verdict] || ""}">
      <div class="rec-top"><span class="rec-verdict">${escapeHtml(rec.verdict)}</span><span class="rec-conv">conviction ${fmtPct(rec.conviction)}</span></div>
      <p>${escapeHtml(rec.rationale || "")}</p>
    </div>` : "";
  const raised = raisedOf(c);
  const edgarUrl = raw.edgar_url || "";
  const filingUrl = raw.filing_url || edgarUrl;
  const cta = `
    <div class="drawer-cta">
      ${c.website && c.website_verified ? `<a class="primary" href="${escapeHtml(c.website)}" target="_blank" rel="noopener">Visit website ↗</a>` : ""}
      ${filingUrl ? `<a href="${escapeHtml(filingUrl)}" target="_blank" rel="noopener">SEC Form D ↗</a>` : ""}
      ${edgarUrl ? `<a href="${escapeHtml(edgarUrl)}" target="_blank" rel="noopener">All EDGAR filings ↗</a>` : ""}
    </div>`;

  $("drawer").innerHTML = `
    <button class="close" aria-label="Close">×</button>
    <h2>${escapeHtml(c.name)} ${verifiedBadge(c)}</h2>
    <div class="memo-sub">${escapeHtml(m.one_liner || c.description || "")} <span class="badge-gen">${escapeHtml(m.generated_by || "heuristic")}</span></div>
    ${recHtml}
    <div class="memo-grid">
      <div class="memo-kv"><div class="k">Category</div><div class="v">${escapeHtml(m.market_category || c.ai_category || "—")}</div></div>
      <div class="memo-kv"><div class="k">Stage</div><div class="v">${escapeHtml(stageOf(c) || "—")}</div></div>
      <div class="memo-kv"><div class="k">Capital raised</div><div class="v">${raised ? fmtMoney(raised) : "—"}</div></div>
      <div class="memo-kv"><div class="k">Jurisdiction</div><div class="v">${escapeHtml(c.jurisdiction || "—")}</div></div>
    </div>
    ${foundersHtml(c.founders)}
    ${scoreBarsHtml(c.scores)}
    ${m.thesis ? `<div class="memo-sec"><h4>Investment thesis</h4><p>${escapeHtml(m.thesis)}</p></div>` : ""}
    ${competitiveHtml(c.competitive)}
    ${risks ? `<div class="memo-sec"><h4>Key risks</h4><ul>${risks}</ul></div>` : ""}
    ${verificationHtml(c)}
    ${cta}
  `;
  $("drawer").hidden = false;
  $("drawerOverlay").hidden = false;
  $("drawer").scrollTop = 0;
  $("drawer").querySelector(".close").addEventListener("click", closeMemo);
}
function closeMemo() { $("drawer").hidden = true; $("drawerOverlay").hidden = true; }

function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
document.addEventListener("click", (e) => { if (e.target.id === "drawerOverlay") closeMemo(); });

load();

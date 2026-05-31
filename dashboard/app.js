"use strict";

// ---------------------------------------------------------------------------
// AI Incorporation Scout — static dashboard front-end.
// Reads the precomputed data.json (produced by `python -m scout export`) and
// renders a filterable / sortable / searchable investor view, grouped by month.
// ---------------------------------------------------------------------------

const state = {
  data: null,
  companies: [],
  filtered: [],
  filters: { aiOnly: true, category: "", month: "", minScore: 0, sort: "score", query: "" },
};

const $ = (id) => document.getElementById(id);
const fmtPct = (x) => `${Math.round((x || 0) * 100)}%`;
const escapeHtml = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
function monthLabel(ym) {
  if (!ym || ym === "unknown") return "Unknown date";
  const [y, m] = ym.split("-");
  return `${MONTH_NAMES[parseInt(m, 10) - 1] || "?"} ${y}`;
}

async function load() {
  try {
    const res = await fetch("data.json", { cache: "no-store" });
    state.data = await res.json();
  } catch (e) {
    $("groups").innerHTML = `<div class="empty">Could not load data.json. Run <code>python -m scout run --source sample --research --export</code> first.</div>`;
    return;
  }
  state.companies = state.data.companies || [];
  initControls();
  renderStats();
  renderLeaderboard();
  renderTrends();
  apply();

  if (state.data.generated_at) {
    $("generatedAt").textContent = `Last updated ${new Date(state.data.generated_at).toLocaleString()}`;
  }
}

// --- Stat cards ------------------------------------------------------------
function renderStats() {
  const s = state.data.stats || {};
  const verified = state.companies.filter((c) => c.verified_real).length;
  const cards = [
    { num: s.total ?? 0, lbl: "Companies discovered" },
    { num: s.ai_total ?? 0, lbl: "AI-related", accent: true },
    { num: verified, lbl: "Verified real" },
    { num: fmtPct(s.avg_score ?? 0), lbl: "Avg confidence" },
  ];
  $("stats").innerHTML = cards
    .map((c) => `<div class="stat"><div class="num ${c.accent ? "accent" : ""}">${escapeHtml(c.num)}</div><div class="lbl">${escapeHtml(c.lbl)}</div></div>`)
    .join("");
}

// --- Leaderboard -----------------------------------------------------------
const VERDICT_CLASS = {
  "Strong interest": "v-strong",
  "Track closely": "v-track",
  "Monitor": "v-monitor",
  "Pass for now": "v-pass",
};

function renderLeaderboard() {
  const lb = state.data.leaderboard || [];
  if (!lb.length) { $("leaderboardPanel").hidden = true; return; }
  $("leaderboard").innerHTML = lb
    .map((c, i) => `
      <button class="lb-row" data-memo="${escapeHtml(c.id)}">
        <span class="lb-rank">${i + 1}</span>
        <span class="lb-score">${c.overall ?? "—"}</span>
        <span class="lb-main">
          <span class="lb-name">${escapeHtml(c.name)}</span>
          <span class="lb-cat">${escapeHtml(c.ai_category || "")}</span>
        </span>
        ${c.verdict ? `<span class="verdict ${VERDICT_CLASS[c.verdict] || ""}">${escapeHtml(c.verdict)}</span>` : ""}
      </button>`)
    .join("");
  $("leaderboard").querySelectorAll("[data-memo]").forEach((b) =>
    b.addEventListener("click", () => openMemo(b.getAttribute("data-memo")))
  );
}

// --- Trends ----------------------------------------------------------------
function renderTrends() {
  const t = state.data.trends || {};
  // Month bars
  const months = t.ai_by_month || [];
  const max = Math.max(1, ...months.map((m) => m.count));
  $("monthBars").innerHTML = months
    .map((m) => {
      const h = Math.round((m.count / max) * 100);
      return `<div class="bar-col"><div class="bar" style="height:${h}%" data-count="${m.count}"></div><div class="bar-label">${monthLabel(m.month).split(" ")[0]}</div></div>`;
    })
    .join("") || '<div class="mom-empty">No data</div>';

  // Categories
  const cats = t.categories || [];
  const catMax = Math.max(1, ...cats.map((c) => c.count));
  $("catList").innerHTML = cats.slice(0, 6)
    .map((c) => `<div class="catrow"><span class="nm">${escapeHtml(c.category)}</span><span class="ct">${c.count}</span><div class="track"><div class="fill" style="width:${(c.count / catMax) * 100}%"></div></div></div>`)
    .join("") || '<div class="mom-empty">No data</div>';

  // Momentum
  const up = (t.accelerating || []).map((r) => `<div class="mom-row"><span class="pill up">▲ +${r.delta}</span><span>${escapeHtml(r.category)}</span></div>`);
  const down = (t.cooling || []).map((r) => `<div class="mom-row"><span class="pill down">▼ ${r.delta}</span><span>${escapeHtml(r.category)}</span></div>`);
  const mom = [...up, ...down];
  $("momentum").innerHTML = mom.length ? mom.join("") : '<div class="mom-empty">Need ≥2 months of data to compute momentum.</div>';

  // Geography
  const geo = t.geography || [];
  const geoMax = Math.max(1, ...geo.map((g) => g.count));
  $("geoList").innerHTML = geo.slice(0, 6)
    .map((g) => `<div class="catrow"><span class="nm">${escapeHtml(g.jurisdiction)}</span><span class="ct">${g.count}</span><div class="track"><div class="fill" style="width:${(g.count / geoMax) * 100}%"></div></div></div>`)
    .join("") || '<div class="mom-empty">No data</div>';
}

// --- Controls --------------------------------------------------------------
function initControls() {
  const cats = [...new Set(state.companies.filter((c) => c.ai_category).map((c) => c.ai_category))].sort();
  $("category").innerHTML = `<option value="">All categories</option>` + cats.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");

  const months = state.data.months || [];
  $("month").innerHTML = `<option value="">All months</option>` + months.map((m) => `<option value="${m}">${monthLabel(m)}</option>`).join("");

  $("aiOnly").addEventListener("change", (e) => { state.filters.aiOnly = e.target.checked; apply(); });
  $("category").addEventListener("change", (e) => { state.filters.category = e.target.value; apply(); });
  $("month").addEventListener("change", (e) => { state.filters.month = e.target.value; apply(); });
  $("sort").addEventListener("change", (e) => { state.filters.sort = e.target.value; apply(); });
  $("minScore").addEventListener("input", (e) => {
    state.filters.minScore = e.target.value / 100;
    $("minScoreLabel").textContent = `${e.target.value}%`;
    apply();
  });
  $("search").addEventListener("input", debounce((e) => { runQuery(e.target.value); }, 200));

  const examples = [
    "AI infrastructure companies founded this month",
    "developer tools last 30 days",
    "healthcare AI in California",
    "high confidence agents",
  ];
  $("examples").innerHTML = examples.map((q) => `<span class="chip">${escapeHtml(q)}</span>`).join("");
  document.querySelectorAll(".chip").forEach((ch) =>
    ch.addEventListener("click", () => { $("search").value = ch.textContent; runQuery(ch.textContent); })
  );
}

// --- Natural-language query (stretch goal 7) -------------------------------
// Lightweight intent parser: maps free text onto the existing filter controls.
function runQuery(text) {
  const q = (text || "").toLowerCase().trim();
  state.filters.query = q;

  // category synonyms -> canonical category
  const catMap = {
    "infrastructure": "AI Infrastructure", "infra": "AI Infrastructure",
    "developer tool": "Developer Tools", "devtool": "Developer Tools", "dev tool": "Developer Tools",
    "agent": "AI Agents", "agentic": "AI Agents",
    "vision": "Computer Vision",
    "nlp": "NLP / Language", "language": "NLP / Language", "speech": "NLP / Language", "voice": "NLP / Language",
    "robot": "Robotics",
    "health": "Healthcare AI", "clinical": "Healthcare AI", "medical": "Healthcare AI",
    "fintech": "Fintech AI", "finance": "Fintech AI", "trading": "Fintech AI",
    "generative": "Generative Media", "media": "Generative Media",
    "analytics": "Data / Analytics", "data": "Data / Analytics",
  };
  let matchedCat = "";
  for (const [k, v] of Object.entries(catMap)) {
    if (q.includes(k)) { matchedCat = v; break; }
  }
  if (matchedCat && [...$("category").options].some((o) => o.value === matchedCat)) {
    $("category").value = matchedCat;
    state.filters.category = matchedCat;
  } else if (!matchedCat) {
    // don't clobber an explicit dropdown choice unless user typed something categorical
  }

  // time windows
  let dateFloor = null;
  const months = state.data.months || [];
  if (q.includes("this month") && months[0]) {
    $("month").value = months[0];
    state.filters.month = months[0];
  } else {
    const days = q.match(/last\s+(\d+)\s+days?/);
    if (q.includes("last 30 days") || (days && parseInt(days[1], 10))) {
      const n = days ? parseInt(days[1], 10) : 30;
      const d = new Date();
      d.setDate(d.getDate() - n);
      dateFloor = d.toISOString().slice(0, 10);
      $("month").value = "";
      state.filters.month = "";
    }
  }
  state.filters._dateFloor = dateFloor;

  // confidence intent
  if (q.includes("high confidence") || q.includes("strong")) {
    $("minScore").value = 75;
    $("minScoreLabel").textContent = "75%";
    state.filters.minScore = 0.75;
  }

  apply();
}

// --- Filtering / sorting / rendering --------------------------------------
function apply() {
  const f = state.filters;
  let rows = state.companies.slice();

  if (f.aiOnly) rows = rows.filter((c) => c.is_ai);
  if (f.category) rows = rows.filter((c) => c.ai_category === f.category);
  if (f.month) rows = rows.filter((c) => c.month === f.month);
  if (f.minScore > 0) rows = rows.filter((c) => (c.ai_score || 0) >= f.minScore);
  if (f._dateFloor) rows = rows.filter((c) => (c.formation_date || "") >= f._dateFloor);

  if (f.query) {
    const terms = f.query.split(/\s+/).filter((t) => t.length > 2 &&
      !["this", "month", "last", "days", "companies", "company", "founded", "show", "the", "with", "high", "confidence", "and", "for"].includes(t));
    if (terms.length) {
      rows = rows.filter((c) => {
        const hay = `${c.name} ${c.description} ${c.ai_category} ${c.jurisdiction} ${(c.ai_signals || []).join(" ")}`.toLowerCase();
        return terms.every((t) => hay.includes(t));
      });
    }
  }

  rows.sort((a, b) => {
    if (f.sort === "name") return a.name.localeCompare(b.name);
    if (f.sort === "date") return (b.formation_date || "").localeCompare(a.formation_date || "");
    return (b.ai_score || 0) - (a.ai_score || 0);
  });

  state.filtered = rows;
  render();
}

function render() {
  const rows = state.filtered;
  $("resultMeta").textContent = `${rows.length} ${rows.length === 1 ? "company" : "companies"} shown`;
  $("empty").hidden = rows.length !== 0;

  // Group by month (preserve sort within group via stable iteration).
  const groups = {};
  const order = [];
  for (const c of rows) {
    const m = c.month || "unknown";
    if (!groups[m]) { groups[m] = []; order.push(m); }
    groups[m].push(c);
  }
  // When sorting by score/name we still bucket by month; order months desc.
  order.sort((a, b) => (b === "unknown" ? -1 : a === "unknown" ? 1 : b.localeCompare(a)));

  $("groups").innerHTML = order
    .map((m) => `
      <div class="month-group">
        <div class="month-head">${monthLabel(m)} <span class="count">${groups[m].length}</span></div>
        <div class="cards">${groups[m].map(cardHtml).join("")}</div>
      </div>`)
    .join("");

  document.querySelectorAll("[data-memo]").forEach((btn) =>
    btn.addEventListener("click", () => openMemo(btn.getAttribute("data-memo")))
  );
}

function scoreClass(s) { return s >= 0.75 ? "hi" : s >= 0.5 ? "mid" : "lo"; }

function verifiedBadge(c) {
  if (!c.verified_real) return "";
  const prov = (c.verification || []).join(" · ");
  const edgarUrl = (c.raw && c.raw.edgar_url) || "";
  const title = `Verified real — ${prov || "authoritative registry"}`;
  if (edgarUrl) {
    return `<a class="vbadge" href="${escapeHtml(edgarUrl)}" target="_blank" rel="noopener" title="${escapeHtml(title)}">✓ Verified</a>`;
  }
  return `<span class="vbadge" title="${escapeHtml(title)}">✓ Verified</span>`;
}

function cardHtml(c) {
  const edgarUrl = (c.raw && c.raw.edgar_url) || "";
  const link = c.website && c.website_verified ? c.website : edgarUrl;
  const linkLabel = c.website && c.website_verified
    ? c.website.replace(/^https?:\/\//, "").replace(/\/$/, "")
    : edgarUrl ? "View SEC filing" : "";
  const host = link ? linkLabel : "";
  const sig = (c.ai_signals || []).slice(0, 3).map((s) => `<span class="tag">${escapeHtml(s)}</span>`).join("");
  const cat = c.ai_category ? `<span class="tag cat">${escapeHtml(c.ai_category)}</span>` : "";
  const hasAnalysis = c.memo || c.scores || c.competitive;
  const memoBtn = hasAnalysis ? `<button class="memo-btn" data-memo="${escapeHtml(c.id)}">📄 Analysis</button>` : "";
  const rec = c.recommendation;
  const recBadge = rec ? `<span class="verdict ${VERDICT_CLASS[rec.verdict] || ""}" title="Opportunity ${rec.overall}/100">${escapeHtml(rec.verdict)}</span>` : "";
  const oppTag = c.scores ? `<span class="tag opp-tag">opp ${c.scores.overall}</span>` : "";
  return `
    <div class="card">
      <div class="card-top">
        <div>
          <h3>${escapeHtml(c.name)} ${verifiedBadge(c)}</h3>
          <div class="sub">${escapeHtml(c.jurisdiction || "—")} · formed ${escapeHtml(c.formation_date || "?")} · ${escapeHtml(c.source)}</div>
        </div>
        <div class="score ${scoreClass(c.ai_score)}">${fmtPct(c.ai_score)}</div>
      </div>
      ${c.description ? `<p class="desc">${escapeHtml(c.description)}</p>` : ""}
      <div class="tags">${cat}${recBadge}${oppTag}${sig}</div>
      <div class="card-foot">
        ${host ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(host)} ↗</a>` : `<span class="sub">no website yet</span>`}
        ${memoBtn}
      </div>
    </div>`;
}

// --- Memo drawer -----------------------------------------------------------
const DIM_LABELS = {
  team_quality: "Team", market_size: "Market size", product_differentiation: "Differentiation",
  technical_complexity: "Technical", defensibility: "Defensibility", timing: "Timing",
};

function scoreBarsHtml(scores) {
  if (!scores || !scores.dimensions) return "";
  const rows = Object.entries(scores.dimensions)
    .map(([k, v]) => `
      <div class="dim">
        <div class="dim-top"><span>${escapeHtml(DIM_LABELS[k] || k)}</span><b>${v.score}</b></div>
        <div class="dim-track"><div class="dim-fill" style="width:${v.score}%"></div></div>
        <div class="dim-reason">${escapeHtml(v.reason || "")}</div>
      </div>`)
    .join("");
  return `
    <div class="memo-sec">
      <h4>Opportunity score — ${scores.overall}/100 <span class="badge-gen">confidence ${fmtPct(scores.confidence)}</span></h4>
      <div class="dims">${rows}</div>
    </div>`;
}

function foundersHtml(founders) {
  if (!founders || !founders.length) return "";
  const items = founders.map((f) => `
    <div class="founder">
      <div class="founder-top"><b>${escapeHtml(f.name)}</b><span class="founder-role">${escapeHtml(f.role || "")}</span></div>
      <div class="founder-bg">${escapeHtml(f.background || "")}</div>
      <div class="founder-meta">
        ${(f.previous_companies || []).map((p) => `<span class="tag">${escapeHtml(p)}</span>`).join("")}
        ${f.profile_url ? `<a href="${escapeHtml(f.profile_url)}" target="_blank" rel="noopener">profile ↗</a>` : ""}
      </div>
    </div>`).join("");
  const src = founders[0]?.source || "";
  return `<div class="memo-sec"><h4>Founding team <span class="badge-gen">${escapeHtml(src)}</span></h4>${items}</div>`;
}

function competitiveHtml(comp) {
  if (!comp) return "";
  const leaders = (comp.leaders || []).map((l) => `<span class="tag cat">${escapeHtml(l)}</span>`).join("");
  const adj = (comp.adjacent || []).map((a) => `<span class="tag">${escapeHtml(a)}</span>`).join("");
  return `
    <div class="memo-sec">
      <h4>Competitive landscape</h4>
      <p>${escapeHtml(comp.positioning || "")}</p>
      <div class="comp-block"><div class="k">Category leaders</div><div class="tags">${leaders || "—"}</div></div>
      <div class="comp-block"><div class="k">Discovered peers</div><div class="tags">${adj || "<span class='sub'>none yet in dataset</span>"}</div></div>
    </div>`;
}

function verificationHtml(c) {
  const prov = c.verification || [];
  const edgarUrl = (c.raw && c.raw.edgar_url) || "";
  if (!prov.length && !edgarUrl) return "";
  const items = prov.map((p) => `<li>${escapeHtml(p)}</li>`).join("");
  const filing = edgarUrl
    ? `<a class="memo-btn" href="${escapeHtml(edgarUrl)}" target="_blank" rel="noopener">View SEC filing (provenance) ↗</a>`
    : "";
  const status = c.verified_real
    ? `<span class="vbadge">✓ Verified real</span>`
    : `<span class="badge-gen">unverified</span>`;
  return `
    <div class="memo-sec">
      <h4>Verification ${status}</h4>
      ${items ? `<ul>${items}</ul>` : "<p>No authoritative signal found.</p>"}
      ${filing}
    </div>`;
}

function openMemo(id) {
  const c = state.companies.find((x) => x.id === id);
  if (!c) return;
  const m = c.memo || {};
  const rec = c.recommendation;
  const risks = (m.risks || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
  const recHtml = rec ? `
    <div class="rec ${VERDICT_CLASS[rec.verdict] || ""}">
      <div class="rec-top"><span class="rec-verdict">${escapeHtml(rec.verdict)}</span><span class="rec-conv">conviction ${fmtPct(rec.conviction)}</span></div>
      <p>${escapeHtml(rec.rationale || "")}</p>
    </div>` : "";

  $("drawer").innerHTML = `
    <button class="close" aria-label="Close">×</button>
    <h2>${escapeHtml(c.name)}</h2>
    <div class="memo-sub">${escapeHtml(m.one_liner || c.description || "")} <span class="badge-gen">${escapeHtml(m.generated_by || "heuristic")}${m.website_analyzed ? " · site analyzed" : ""}</span></div>
    ${recHtml}
    <div class="memo-grid">
      <div class="memo-kv"><div class="k">Market category</div><div class="v">${escapeHtml(m.market_category || c.ai_category || "—")}</div></div>
      <div class="memo-kv"><div class="k">Estimated stage</div><div class="v">${escapeHtml(m.estimated_stage || "—")}</div></div>
      <div class="memo-kv"><div class="k">AI confidence</div><div class="v">${fmtPct(c.ai_score)}</div></div>
      <div class="memo-kv"><div class="k">Jurisdiction</div><div class="v">${escapeHtml(c.jurisdiction || "—")}</div></div>
    </div>
    ${scoreBarsHtml(c.scores)}
    ${m.thesis ? `<div class="memo-sec"><h4>Investment thesis</h4><p>${escapeHtml(m.thesis)}</p></div>` : ""}
    ${foundersHtml(c.founders)}
    ${competitiveHtml(c.competitive)}
    ${m.reasoning ? `<div class="memo-sec"><h4>Reasoning</h4><p>${escapeHtml(m.reasoning)}</p></div>` : ""}
    ${risks ? `<div class="memo-sec"><h4>Key risks</h4><ul>${risks}</ul></div>` : ""}
    ${verificationHtml(c)}
    ${c.website && c.website_verified ? `<div class="memo-sec"><a class="memo-btn" href="${escapeHtml(c.website)}" target="_blank" rel="noopener">Visit website ↗</a></div>` : ""}
  `;
  $("drawer").hidden = false;
  $("drawerOverlay").hidden = false;
  $("drawer").querySelector(".close").addEventListener("click", closeMemo);
}
function closeMemo() { $("drawer").hidden = true; $("drawerOverlay").hidden = true; }

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMemo(); });
document.addEventListener("click", (e) => { if (e.target.id === "drawerOverlay") closeMemo(); });

load();

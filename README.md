# AI Incorporation Scout Agent

> An autonomous agent that discovers newly formed companies from public sources,
> classifies how AI-related they are, builds intelligence on them, and surfaces
> the results in an investor-facing dashboard — *before* they hit mainstream
> startup databases.

This is a **Week 1** submission for the AI Incorporation Scout assignment, plus
**most of the Week 2 stretch goals**: a multi-agent *Venture Analyst Swarm*
(research memos, founder discovery, opportunity scoring, competitive landscapes,
and a final recommendation), trend detection, a natural-language query
interface, and an always-on GitHub Actions deployment.

---

## What it does

A pipeline of cooperating, specialized agents — the **Venture Analyst Swarm** —
turns a raw public record into an investor-ready recommendation:

```
   DISCOVERY → CLASSIFIER → RESEARCH → FOUNDER → SCORING → MARKET → REPORTING
   (sources)   (AI score)   (memo +    (team    (6-dim   (leaders  (verdict +
                            website)   profiles) opp)     + peers)  rationale)
                                          │
                                          ▼
                                    STORE (SQLite) ── export ──▶ static dashboard
                                                                  (GitHub Pages)
```

1. **Discovery** — collect newly formed company records from public sources
   (live SEC EDGAR Form D filings + a bundled offline sample dataset).
2. **Classifier** — transparent, calibrated AI-relatedness score (`0..1`) and a
   subsector category. Optional LLM upgrade.
3. **Research** *(stretch 1)* — visit the website, estimate market & stage, draft
   a one-page investment memo.
4. **Founder** *(stretch 2)* — structured founder/executive profiles.
5. **Scoring** *(stretch 4)* — a 6-dimension opportunity score + confidence.
6. **Market** *(stretch 5)* — competitive landscape: real category leaders,
   discovered peers, white space.
7. **Reporting** *(stretch 3)* — synthesize into a final recommendation
   (verdict + conviction + rationale).
8. **Store & Export** — persist to SQLite (idempotent upserts) and emit a
   precomputed `data.json` powering a static dashboard with a Top-Opportunities
   leaderboard, grouping/sorting/filtering, trend charts *(stretch 6)*, and
   natural-language search *(stretch 7)*.

---

## Quick start

**Requirements:** Python 3.10+. The core pipeline uses only the standard
library — **no install required**.

```bash
# 1. Build the sample dataset from REAL Delaware incorporations.
#    Pulls firms *incorporated in DE* filing a Form D (last ~45 days) from
#    SEC EDGAR — every record has a verifiable SEC CIK. No scraping, no API key.
python -m scout gen-sample --max-age-days 45

# 2. Discover + classify + research from the sample, then export
python -m scout run --source sample --research --export

# 3. Open the dashboard
cd dashboard && python -m http.server 8000
# visit http://localhost:8000
```

That's it. The committed `dashboard/data.json` means the dashboard also works
the instant you deploy it — no pipeline run needed.

### How we get real Delaware firms (and prove they're real)

Delaware has no public bulk API, and its ICIS portal explicitly **discourages
data mining** (and is anti-automation, so scraping it is both fragile and against
its terms). Instead we use a **legitimate, free, official** signal:

> **SEC EDGAR's state-of-incorporation filter.** Newly formed Delaware entities
> that raise any private capital file a **Form D**, and EDGAR lets you query for
> filers whose state of *incorporation* is `DE`
> (`locationType=incorporated&locationCodes=DE`).

This gives real DE-incorporated companies, in their first weeks, each with a
**verifiable SEC CIK and a public filing** — months before they hit mainstream
startup databases. No API key, no anti-bot fight, updates continuously.

```bash
# The reliable Delaware feed (EDGAR-backed)
python -m scout run --source delaware \
  --query '"artificial intelligence" OR robotics OR autonomous' \
  --days-back 60 --research --export
```

**Every company is verified real.** On ingest each record is checked against
independent, auditable signals and tagged `verified_real` with provenance:

- an **SEC EDGAR CIK** (a registered filer with a public filing), and/or
- a **website that resolves** over HTTP/DNS.

The dashboard shows a **✓ Verified** badge on each card that links straight to
the source SEC filing, plus a "Verification" section in the analysis drawer.

> The original ICIS scraper is kept as a separate, best-effort source
> (`--source delaware_icis`) for completeness, but it is **not** used for the
> sample or the scheduled refresh because the portal is unreliable.

### Run against the live SEC EDGAR source

Form D filings (notices of exempt securities offerings) are filed by recently
formed entities raising their first private capital — a strong leading signal
for "newly formed company" discovery.

```bash
python -m scout run \
  --source sec_edgar \
  --query '"artificial intelligence"' \
  --days-back 120 --limit 50 \
  --user-agent "AI-Incorporation-Scout/0.1 (you@example.com)" \
  --research --export
```

> SEC's fair-access policy asks for a descriptive `User-Agent` with a contact
> email. No API key is required.

### Optional: LLM-powered classification & memos

```bash
pip install -r requirements.txt        # installs the optional `openai` client
export OPENAI_API_KEY=sk-...
python -m scout run --source sample --llm --research --export
```

If the key or package is missing, the pipeline **automatically falls back** to
the heuristic classifier and heuristic memos — it never hard-fails.

### CLI reference

| Command | Description |
| --- | --- |
| `python -m scout gen-sample` | Pull real DE-incorporated firms (EDGAR) into the sample JSON |
| `python -m scout run` | Discover → verify → classify → (research) → store |
| `python -m scout export` | Re-export `dashboard/data.json` from the DB |
| `python -m scout stats` | Print database stats |
| `python -m scout verify-links` | Verify every website URL in the sample JSON resolves |

Useful `run` flags: `--source {sample,delaware,delaware_icis,sec_edgar}`, `--limit N`,
`--max-age-days N`, `--llm`, `--research`, `--no-fetch-site`, `--export`,
`--query`, `--days-back`, `--forms`, `--user-agent`.

---

## Deploying the dashboard to GitHub Pages

There are two supported paths:

**A. GitHub Actions (recommended, always-on — stretch goal 8).**
`.github/workflows/deploy.yml` regenerates the dataset from the **reliable
EDGAR-backed Delaware feed**, runs the full analyst swarm, commits the refreshed
data, and publishes `dashboard/` to Pages on every push, on a **weekly schedule**
(keeping the 30-day discovery window current), and on manual dispatch — so the public
dashboard keeps refreshing itself with no manual intervention.

> One-time setup: repo **Settings → Pages → Build and deployment → Source =
> GitHub Actions**. The dashboard then serves at the site root.

**B. Deploy from branch (zero config).**
Set **Settings → Pages → Source = Deploy from a branch**, branch `main`, folder
`/ (root)`. The root `index.html` redirects to `./dashboard/`, which reads its
committed `data.json`.

To refresh data manually: re-run the pipeline with `--export` and commit the
updated `dashboard/data.json`.

---

## Architecture

```
scout/
├── __main__.py          # CLI entrypoint (argparse)
├── pipeline.py          # Venture Analyst Swarm orchestration (stretch 3)
├── models.py            # Company dataclass + stable IDs (idempotent upserts)
├── db.py                # SQLite storage layer (schema, upsert, queries, stats)
├── export.py            # DB → dashboard/data.json + trends + leaderboard
├── seed.py              # deterministic sample-dataset generator
├── score.py             # opportunity scoring engine (stretch 4)
├── founders.py          # founder discovery agent (stretch 2)
├── edgar_detail.py      # real officers/stage/capital from Form D XML
├── competitive.py       # competitive landscape generator (stretch 5)
├── recommend.py         # reporting agent: final recommendation (stretch 3)
├── sources/             # pluggable data-source connectors
│   ├── base.py          #   Source ABC
│   ├── sample.py        #   offline bundled dataset
│   └── sec_edgar.py     #   live SEC EDGAR Form D full-text search
├── classify/            # AI-relatedness classification
│   ├── heuristic.py     #   transparent, calibrated keyword/logistic scorer
│   └── llm.py           #   optional OpenAI classifier (graceful fallback)
├── research/            # autonomous research agent (stretch 1)
│   └── memo.py          #   website visit + investment-memo generation
└── data/
    └── sample_companies.json

dashboard/               # static, GitHub Pages–ready front-end
├── index.html           #   leaderboard, trends, filters, NL search, drawer
├── styles.css
├── app.js
└── data.json            # precomputed export (committed for instant deploy)

index.html               # root redirect → dashboard/ (for branch-based Pages)
.github/workflows/
└── deploy.yml           # always-on: run pipeline + deploy Pages (stretch 8)
```

### Data model

A `Company` carries collection metadata (name, source, jurisdiction, formation
date, website, description), classifier output (`ai_score`, `is_ai`,
`ai_signals`, `ai_category`), and an optional research `memo`. IDs are a
deterministic hash of `source + source_id`, so re-running the pipeline
**upserts** rather than duplicating.

### Classifier

The default heuristic classifier is intentionally **transparent**: every score
ships with the exact signals that produced it (e.g. `"machine learning (name)"`),
which matters for investor trust and for debugging false positives. Weighted
evidence (strong phrases like *"large language model"* count more than weak,
ambiguous tokens like a bare *"AI"*) is squashed through a logistic function
into a calibrated `0..1` confidence, with field weighting (a name match counts
more than a description match) and whole-word matching to avoid false positives
like *"Mountain **AI**r"*.

### The analyst swarm (stretch goals 1–5)

For companies above a confidence threshold, a sequence of specialized agents
runs (orchestrated in `pipeline.py`):

- **Research** (`research/memo.py`) optionally fetches the website
  (dependency-free HTML→text), estimates market & stage, and drafts a memo:
  one-liner, thesis, reasoning, market read, risks. Degrades *LLM prose →
  site-enriched heuristic → metadata-only heuristic*; always produces a memo.
- **Founder** (`founders.py` + `edgar_detail.py`) prefers the **real officers and
  directors named in the company's SEC Form D filing** (`"source": "sec_filing"`) —
  actual people, with role, city/state, and a LinkedIn people-search link. When a
  filing has no named people it falls back to LLM website extraction (`--llm`) or
  clearly **labeled synthetic** profiles, so the product is always demonstrable.
- **Scoring** (`score.py`) produces six explainable 0–100 sub-scores (team,
  market, differentiation, technical, defensibility, timing) blending category
  priors, company evidence, and a deterministic per-company variation, plus an
  overall score and an evidence-based confidence.
- **Market** (`competitive.py`) maps each company to real category leaders (from
  a curated KB), discovered peers in the dataset, and a white-space prompt.
- **Reporting** (`recommend.py`) synthesizes the above into a verdict
  (*Strong interest → Track → Monitor → Pass*), a conviction level, and a
  rationale citing the strongest/weakest signals.

### Trend detection (stretch goal 6)

`export.py` precomputes AI discovery momentum by month, category & geographic
distributions, and which categories are accelerating vs. cooling month over
month — rendered as charts in the dashboard's **Trend Intelligence** panel.

### Natural language interface (stretch goal 7)

The dashboard search box accepts queries like *"AI infrastructure companies
founded this month"* or *"developer tools last 30 days"*. A lightweight
client-side intent parser maps category synonyms, time windows, and confidence
intent onto the existing filter controls — no backend required.

---

## Design decisions

- **Standard-library core, optional everything else.** The pipeline runs with
  zero `pip install`. The LLM is an *enhancement*, never a dependency, so the
  project is reproducible on any machine. This keeps the "unlock" friction-free.
- **SQLite, not Postgres.** A single-file DB keeps the project portable and
  zero-setup while still giving real schema, indexes, and idempotent upserts.
  The `db.py` interface is small enough to swap for Postgres later.
- **Static dashboard with precomputed data.** All aggregation happens in Python
  and is baked into `data.json`. The front-end stays dependency-free and
  deploys to GitHub Pages with no build step — exactly the assignment's target.
- **Pluggable source connectors.** A `Source` ABC + registry means adding
  Companies House (UK), OpenCorporates, or state registries is a single new
  file. SEC EDGAR Form D was chosen as the first *live* source because it is
  free, key-less, and a genuine early-formation signal.
- **Fail-soft everywhere.** A bad record or flaky network degrades a single
  item, never the whole run — essential for an unattended, continuously running
  agent.
- **Transparent scoring.** Explainable signals over a black box, so an investor
  can trust (and audit) why a company surfaced.

---

## Known limitations

- **Sample data uses real public companies.** The offline demo dataset lists real AI
  companies with **verified working websites** (checked on ingest via DNS/HTTP).
  Formation dates and jurisdictions are illustrative so the pipeline runs
  offline; live `sec_edgar` pulls real filings. Non-AI noise records omit
  websites (typical for early local formations).
- **Form D ≠ all new companies — and skews to hardware/robotics.** EDGAR Form D
  captures entities raising *priced/exempt* rounds. Many AI **software** startups
  raise on SAFEs (no Form D), so the operating-company slice that surfaces skews
  toward robotics/hardware (which file Form D for priced rounds). We drop pooled
  funds/SPVs to keep real operating companies. It's a high-signal *slice*, not
  full incorporation coverage; a state-registry connector would broaden the funnel.
- **Founders are real when the filing names them.** Officers/directors come
  straight from the SEC Form D (`"source": "sec_filing"`) with a LinkedIn
  people-search link to reach the actual person. Only when a filing lists no
  individuals do we fall back to LLM extraction or clearly-labeled synthetic
  profiles — and the source is always shown, so nothing masquerades as verified.
- **Opportunity scores are heuristic/illustrative.** They blend category priors
  with available evidence and a deterministic per-company variation — a
  defensible, auditable scaffold, not a calibrated model. They're meant to show
  the *structure*; a real data layer (funding, traction, team graph) plugs in
  behind the same interface.
- **Competitive leaders are a curated snapshot.** Grounded in real companies but
  not exhaustive or live; adjacency grows as the scout discovers more peers.
- **Heuristic classifier has blind spots.** It keys on names/descriptions, so a
  genuinely-AI company with a generic name and no description can be missed
  (false negative), and a buzzword-stuffed non-AI company can score high (false
  positive). The `--llm` path mitigates this.
- **Website fetch is best-effort.** JS-heavy sites yield little text via the
  static fetch; many brand-new companies have no site yet.
- **Stage estimation is coarse.** Inferred from on-page/registry text cues only;
  no funding database is wired in yet.
- **No scheduler included.** Continuous operation (stretch goal 8) is a `cron`/
  GitHub Action away — the pipeline is already idempotent and incremental.

---

## Stretch goals included

- ✅ **Goal 1 — Autonomous Research Agent:** website visit + one-page investment
  memo (market category, stage, thesis, risks, reasoning).
- ✅ **Goal 2 — Founder Discovery Agent:** structured founder/executive profiles
  (LLM website extraction, with labeled-synthetic fallback).
- ✅ **Goal 3 — Venture Analyst Swarm:** cooperating Discovery/Research/Founder/
  Scoring/Market/Reporting agents producing a final recommendation.
- ✅ **Goal 4 — Opportunity Scoring Engine:** six explainable dimensions +
  overall score + confidence.
- ✅ **Goal 5 — Competitive Landscape Generator:** category leaders, discovered
  peers, and white space per company.
- ✅ **Goal 6 — Trend Detection Engine:** month-over-month AI momentum, category
  & geographic distributions, accelerating/cooling sectors.
- ✅ **Goal 7 — Natural Language Interface:** plain-English dashboard queries.
- ✅ **Goal 8 — Always-on platform:** scheduled GitHub Action discovers,
  analyzes, and redeploys the dashboard with no manual intervention.

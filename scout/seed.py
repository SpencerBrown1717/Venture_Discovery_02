"""Build the bundled sample dataset from real Delaware incorporation records.

`gen-sample` pulls recently formed companies *incorporated in Delaware* from SEC
EDGAR (Form D filers with state-of-incorporation = DE) and writes them to
scout/data/sample_companies.json. These are real entities with verifiable SEC
CIK numbers — no synthetic data, no anti-bot scraping.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "data" / "sample_companies.json"

# OR'd AI/frontier-tech terms to surface relevant newly formed DE entities.
AI_QUERY = (
    '"artificial intelligence" OR "machine learning" OR "generative AI" '
    'OR robotics OR "computer vision" OR "neural network" OR "large language model" '
    'OR autonomous OR "deep learning"'
)


def _to_record(company) -> dict:
    return {
        "name": company.name,
        "source": company.source,
        "source_id": company.source_id,
        "jurisdiction": company.jurisdiction,
        "formation_date": company.formation_date,
        "description": company.description,
        "raw": company.raw,
    }


def _enrich(rec: dict) -> dict:
    """Attach real Form D details (officers, stage, capital, industry).

    Returns the record annotated with `founders`, `stage`, and an enriched
    `raw`; sets `raw['is_fund']` so callers can drop pooled investment vehicles.
    """
    from .edgar_detail import fetch_form_d_detail

    raw = rec.get("raw") or {}
    detail = fetch_form_d_detail(
        str(raw.get("cik") or ""),
        str(raw.get("accession") or ""),
        rec.get("name", ""),
    )
    if not detail:
        return rec

    rec["founders"] = detail["related_persons"]
    rec["stage"] = detail["stage"]
    raw.update({
        "industry_group": detail["industry_group"],
        "is_fund": detail["is_fund"],
        "offering_amount": detail["offering_amount"],
        "amount_sold": detail["amount_sold"],
        "revenue_range": detail["revenue_range"],
        "filing_url": detail["filing_url"],
        "stage": detail["stage"],
    })
    rec["raw"] = raw
    # Enrich the description with the real capital signal when present.
    raised = detail["amount_sold"] or detail["offering_amount"]
    if raised:
        rec["description"] = (
            f"{rec.get('description', '').rstrip('.')}. "
            f"Form D reports ${raised:,} {'raised' if detail['amount_sold'] else 'offering'} "
            f"({detail['stage']})."
        )
    return rec


def harvest(*, days_back: int = 45, limit: int = 120, query: str = "",
            include_funds: bool = False) -> list[dict]:
    """Pull real, *operating* DE-incorporated firms from EDGAR.

    1. Discover candidates (AI-biased pass + general fill) via the EDGAR DE feed.
    2. Enrich each with its real Form D details (officers, stage, capital).
    3. Drop pooled investment funds / SPVs by default so the dataset is real
       operating companies caught near formation — what a VC actually wants.
    """
    from .sources.delaware import DelawareSource

    candidates: list[dict] = []
    seen: set[str] = set()
    # Over-fetch: many hits are funds we'll filter out.
    pool = max(limit * 3, 90)

    def collect(src_query: str, cap: int) -> None:
        if cap <= 0:
            return
        source = DelawareSource(days_back=days_back, query=src_query)
        for company in source.fetch(limit=cap):
            key = company.name.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append(_to_record(company))

    if query:
        collect(query, pool)
    else:
        collect(AI_QUERY, int(pool * 0.7))
        collect("", pool - len(candidates))

    kept: list[dict] = []
    for rec in candidates:
        rec = _enrich(rec)
        if not include_funds and (rec.get("raw") or {}).get("is_fund"):
            continue
        kept.append(rec)
        if len(kept) >= limit:
            break

    kept.sort(key=lambda r: r.get("formation_date") or "", reverse=True)
    return kept


def write(
    path: Path | str | None = None,
    *,
    days_back: int = 45,
    limit: int = 120,
    query: str = "",
) -> Path:
    out = Path(path) if path else DATA_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    records = harvest(days_back=days_back, limit=limit, query=query)
    if not records:
        raise RuntimeError(
            "Delaware (EDGAR) harvest returned 0 entities. "
            "Try a larger --max-age-days window or run again later."
        )
    out.write_text(json.dumps(records, indent=2))
    return out

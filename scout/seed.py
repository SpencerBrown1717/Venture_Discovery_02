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


def harvest(*, days_back: int = 45, limit: int = 120, query: str = "") -> list[dict]:
    """Pull real DE-incorporated firms from EDGAR.

    Runs an AI-biased pass first (so the dataset is rich with AI startups), then
    a general pass to fill remaining slots with other recent DE incorporations —
    realistic noise that exercises the classifier.
    """
    from .sources.delaware import DelawareSource

    records: list[dict] = []
    seen: set[str] = set()

    def collect(src_query: str, cap: int) -> None:
        if cap <= 0:
            return
        source = DelawareSource(days_back=days_back, query=src_query)
        for company in source.fetch(limit=cap):
            key = company.name.lower()
            if key in seen:
                continue
            seen.add(key)
            records.append(_to_record(company))

    if query:
        collect(query, limit)
    else:
        ai_cap = max(1, int(limit * 0.6))
        collect(AI_QUERY, ai_cap)
        collect("", limit - len(records))

    records.sort(key=lambda r: r.get("formation_date") or "", reverse=True)
    return records[:limit]


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

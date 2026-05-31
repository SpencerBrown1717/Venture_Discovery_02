"""Core data structures shared across the pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Optional


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def make_company_id(source: str, source_id: str, name: str) -> str:
    """Stable, deterministic id so re-running the pipeline upserts instead of duplicating."""
    basis = f"{source}:{source_id or name}".lower()
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"{source}-{digest}"


@dataclass
class Company:
    """A newly formed company discovered from a public source.

    The fields above the divider are collected during ingestion; the
    `ai_*` fields are populated by the classifier; `memo`/`research` are
    populated by the optional research agent (stretch goal).
    """

    name: str
    source: str
    source_id: str = ""
    jurisdiction: str = ""          # e.g. "CA, USA"
    formation_date: Optional[str] = None  # ISO date the company was formed/registered
    discovered_date: Optional[str] = None  # ISO date the scout first saw it
    website: Optional[str] = None
    website_verified: bool = False  # True only after DNS/HTTP check passes
    verified_real: bool = False     # backed by >=1 authoritative signal
    verification: list[str] = field(default_factory=list)  # provenance strings
    description: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    # --- populated by the classifier ---
    ai_score: float = 0.0           # 0..1 confidence the company is AI-related
    is_ai: bool = False
    ai_signals: list[str] = field(default_factory=list)
    ai_category: str = ""           # best-guess AI subsector

    # --- populated by the Venture Analyst Swarm (optional) ---
    memo: Optional[dict[str, Any]] = None          # research agent (stretch 1)
    founders: list[dict[str, Any]] = field(default_factory=list)  # founder agent (stretch 2)
    scores: Optional[dict[str, Any]] = None        # scoring engine (stretch 4)
    competitive: Optional[dict[str, Any]] = None   # market/competitive agent (stretch 5)
    recommendation: Optional[dict[str, Any]] = None  # reporting agent (stretch 3)

    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_company_id(self.source, self.source_id, self.name)
        if not self.discovered_date:
            self.discovered_date = date.today().isoformat()

    @property
    def month(self) -> str:
        """Formation month bucket (YYYY-MM), falling back to discovery date."""
        anchor = self.formation_date or self.discovered_date or ""
        return anchor[:7] if len(anchor) >= 7 else "unknown"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["month"] = self.month
        return d

    def to_row(self) -> dict[str, Any]:
        """Flattened representation for SQLite (json-encodes nested fields)."""
        return {
            "id": self.id,
            "name": self.name,
            "source": self.source,
            "source_id": self.source_id,
            "jurisdiction": self.jurisdiction,
            "formation_date": self.formation_date,
            "discovered_date": self.discovered_date,
            "website": self.website,
            "website_verified": int(self.website_verified),
            "verified_real": int(self.verified_real),
            "verification": json.dumps(self.verification),
            "description": self.description,
            "ai_score": self.ai_score,
            "is_ai": int(self.is_ai),
            "ai_signals": json.dumps(self.ai_signals),
            "ai_category": self.ai_category,
            "memo": json.dumps(self.memo) if self.memo else None,
            "founders": json.dumps(self.founders) if self.founders else None,
            "scores": json.dumps(self.scores) if self.scores else None,
            "competitive": json.dumps(self.competitive) if self.competitive else None,
            "recommendation": json.dumps(self.recommendation) if self.recommendation else None,
            "raw": json.dumps(self.raw),
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Company":
        return cls(
            id=row["id"],
            name=row["name"],
            source=row["source"],
            source_id=row["source_id"] or "",
            jurisdiction=row["jurisdiction"] or "",
            formation_date=row["formation_date"],
            discovered_date=row["discovered_date"],
            website=row["website"],
            website_verified=bool(row.get("website_verified", 0)),
            verified_real=bool(row.get("verified_real", 0)),
            verification=json.loads(row["verification"]) if row.get("verification") else [],
            description=row["description"] or "",
            ai_score=row["ai_score"] or 0.0,
            is_ai=bool(row["is_ai"]),
            ai_signals=json.loads(row["ai_signals"]) if row["ai_signals"] else [],
            ai_category=row["ai_category"] or "",
            memo=json.loads(row["memo"]) if row["memo"] else None,
            founders=json.loads(row["founders"]) if row["founders"] else [],
            scores=json.loads(row["scores"]) if row["scores"] else None,
            competitive=json.loads(row["competitive"]) if row["competitive"] else None,
            recommendation=json.loads(row["recommendation"]) if row["recommendation"] else None,
            raw=json.loads(row["raw"]) if row["raw"] else {},
        )

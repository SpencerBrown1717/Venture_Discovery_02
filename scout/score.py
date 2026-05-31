"""Startup Opportunity Scoring Engine (stretch goal 4).

Produces explainable 0-100 sub-scores across six venture dimensions plus an
overall score and a confidence estimate. Scores blend three transparent inputs:

  1. Category priors (market size / timing / defensibility differ by subsector).
  2. Company-specific evidence (classifier confidence, signal density,
     description specificity, discovered founder pedigree).
  3. A small deterministic per-company variation (hashed from the id) so peers
     in the same category don't collapse to identical numbers.

Everything is heuristic and *illustrative* — see README limitations. The point
is a defensible, auditable scaffold a real data layer can later plug into.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .models import Company

# Category priors (0-100 baselines per dimension).
MARKET_SIZE = {
    "AI Infrastructure": 88, "NLP / Language": 86, "Healthcare AI": 88,
    "Fintech AI": 85, "Data / Analytics": 82, "Developer Tools": 74,
    "AI Agents": 80, "Computer Vision": 76, "Generative Media": 78,
    "Robotics": 80, "General AI": 75,
}
TIMING = {
    "AI Agents": 90, "AI Infrastructure": 88, "Generative Media": 84,
    "Developer Tools": 82, "Robotics": 80, "NLP / Language": 72,
    "Healthcare AI": 76, "Computer Vision": 74, "Fintech AI": 73,
    "Data / Analytics": 70, "General AI": 72,
}
TECHNICAL = {
    "AI Infrastructure": 88, "Robotics": 86, "Computer Vision": 82,
    "NLP / Language": 80, "Healthcare AI": 74, "AI Agents": 72,
    "Generative Media": 72, "Data / Analytics": 68, "Fintech AI": 68,
    "Developer Tools": 70, "General AI": 70,
}
DEFENSIBILITY = {
    "AI Infrastructure": 78, "Robotics": 80, "Healthcare AI": 80,
    "Fintech AI": 76, "Computer Vision": 72, "Data / Analytics": 64,
    "AI Agents": 60, "Developer Tools": 62, "General AI": 58,
    "NLP / Language": 54, "Generative Media": 52,
}

WEIGHTS = {
    "team_quality": 0.22,
    "market_size": 0.20,
    "product_differentiation": 0.18,
    "technical_complexity": 0.15,
    "defensibility": 0.15,
    "timing": 0.10,
}


def _jitter(company_id: str, salt: str, spread: int = 8) -> int:
    h = hashlib.sha1(f"{company_id}:{salt}".encode()).hexdigest()
    return (int(h[:4], 16) % (2 * spread + 1)) - spread


def _clamp(x: float) -> int:
    return int(max(1, min(100, round(x))))


@dataclass
class ScoringAgent:
    def score(self, company: Company) -> Company:
        cat = company.ai_category or "General AI"
        cid = company.id
        desc = company.description or ""
        n_strong = sum(1 for s in company.ai_signals if "(name)" in s or "(description)" in s)

        # --- team quality ---
        real = [f for f in (company.founders or []) if f.get("source") == "sec_filing"]
        raw = company.raw or {}
        raised = raw.get("amount_sold") or raw.get("offering_amount") or 0
        if real:
            # Real officers/directors from the SEC filing: team strength from
            # team size, board formation, and capital already raised.
            n_officers = sum(1 for f in real if "Officer" in (f.get("role") or ""))
            n_directors = sum(1 for f in real if "Director" in (f.get("role") or ""))
            base = 58 + 5 * min(n_officers, 3) + 3 * min(n_directors, 4)
            if raised >= 10_000_000:
                base += 14
            elif raised >= 3_000_000:
                base += 9
            elif raised > 0:
                base += 4
            team = base + _jitter(cid, "team", 4)
            team_reason = (
                f"{len(real)} named officer(s)/director(s) in SEC filing"
                + (f"; ${raised:,} raised" if raised else "")
            )
        elif company.founders:
            ped = sum(f.get("pedigree", 50) for f in company.founders) / len(company.founders)
            team = ped + _jitter(cid, "team", 5)
            team_reason = (
                f"{len(company.founders)} founder(s) profiled; avg pedigree {int(ped)}/100"
            )
        else:
            team = 50 + 18 * company.ai_score + _jitter(cid, "team")
            team_reason = "No founder profiles yet; proxied from formation-stage signal."

        # --- market size ---
        market = MARKET_SIZE.get(cat, 75) + _jitter(cid, "market", 5)
        market_reason = f"{cat} TAM prior."

        # --- product differentiation: strong-signal density + specificity ---
        diff = 50 + 6 * n_strong + min(15, len(desc) / 20) + _jitter(cid, "diff")
        diff_reason = f"{n_strong} strong AI signal(s); description specificity factored in."

        # --- technical complexity ---
        tech = TECHNICAL.get(cat, 70) + 8 * company.ai_score + _jitter(cid, "tech", 5)
        tech_reason = f"{cat} technical baseline scaled by AI confidence."

        # --- defensibility ---
        defens = DEFENSIBILITY.get(cat, 60) + _jitter(cid, "def")
        defens_reason = f"{cat} moat profile (data/regulatory/network effects)."

        # --- timing ---
        timing = TIMING.get(cat, 72) + _jitter(cid, "time", 5)
        timing_reason = f"Current investor momentum in {cat}."

        dims = {
            "team_quality": {"score": _clamp(team), "reason": team_reason},
            "market_size": {"score": _clamp(market), "reason": market_reason},
            "product_differentiation": {"score": _clamp(diff), "reason": diff_reason},
            "technical_complexity": {"score": _clamp(tech), "reason": tech_reason},
            "defensibility": {"score": _clamp(defens), "reason": defens_reason},
            "timing": {"score": _clamp(timing), "reason": timing_reason},
        }

        overall = sum(dims[k]["score"] * w for k, w in WEIGHTS.items())

        # --- confidence: how much evidence backs these numbers ---
        evidence = 0.0
        evidence += 0.25 if company.website else 0.0
        evidence += min(0.25, len(desc) / 800)
        evidence += min(0.20, len(company.ai_signals) * 0.04)
        evidence += 0.20 if company.founders else 0.0
        evidence += 0.10 * (1 - abs(0.5 - company.ai_score) * 2 if company.ai_score < 0.5 else company.ai_score * 0.2 + 0.1)
        confidence = round(min(0.95, max(0.25, 0.2 + evidence)), 2)

        company.scores = {
            "dimensions": dims,
            "overall": _clamp(overall),
            "confidence": confidence,
        }
        return company

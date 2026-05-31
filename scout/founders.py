"""Founder Discovery Agent (stretch goal 2).

Goal: produce structured founder/executive summaries — names, roles, public
profiles, previous companies, and relevant background.

Reality check: for *brand-new* companies, reliable founder data lives behind
people-data APIs (PeopleDataLabs, Clearbit, LinkedIn) that need paid keys and
are out of scope here. So this agent ships two honest modes:

  * `synthetic` (default): deterministic, clearly-labeled illustrative profiles
    so the end-to-end product and dashboard are fully demonstrable offline.
  * `llm` (optional): extract real names/roles from fetched website text via an
    OpenAI-compatible model, falling back to synthetic on any failure.

Every profile carries a `source` field so nothing masquerades as verified fact.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from .models import Company

FIRST = ["Maya", "Daniel", "Priya", "Liam", "Sofia", "Noah", "Aisha", "Lucas",
         "Elena", "Omar", "Hannah", "Kenji", "Zoe", "Mateo", "Nina", "Arjun",
         "Clara", "Ethan", "Yuki", "Diego", "Lena", "Ravi", "Maya", "Theo"]
LAST = ["Chen", "Patel", "Kim", "Garcia", "Okafor", "Nguyen", "Schmidt", "Rossi",
        "Haddad", "Andersson", "Yamamoto", "Silva", "Cohen", "Mbeki", "Novak",
        "Reyes", "Larsson", "Khan", "Ferraro", "Walsh"]
BIGCOS = ["Google DeepMind", "OpenAI", "Meta AI (FAIR)", "Anthropic", "NVIDIA",
          "Tesla Autopilot", "Apple", "Amazon AWS", "Microsoft Research", "Stripe",
          "Palantir", "Databricks"]
STARTUPS = ["Scale AI", "Hugging Face", "Cohere", "Snorkel AI", "Weights & Biases",
            "Cruise", "Nuro", "Benchling", "Ramp", "Figma"]
UNIS = ["Stanford", "MIT", "CMU", "Berkeley", "Oxford", "ETH Zürich", "Tsinghua",
        "Caltech", "Cambridge", "University of Toronto"]
FIELDS = ["Machine Learning", "Computer Science", "Robotics", "Computational Biology",
          "Electrical Engineering", "Applied Mathematics", "NLP"]
ROLES = ["Co-founder & CEO", "Co-founder & CTO", "Co-founder & Chief Scientist"]


def _rng_ints(seed: str, n: int) -> list[int]:
    out, h = [], hashlib.sha256(seed.encode()).hexdigest()
    for i in range(n):
        out.append(int(h[(i * 4) % 60:(i * 4) % 60 + 4] or "0", 16))
    return out


@dataclass
class FounderAgent:
    use_llm: bool = False
    model: str = "gpt-4o-mini"

    def __post_init__(self) -> None:
        self._client = None
        if self.use_llm:
            try:
                from openai import OpenAI

                if not os.getenv("OPENAI_API_KEY"):
                    raise RuntimeError("OPENAI_API_KEY not set")
                self._client = OpenAI()
            except Exception as exc:  # pragma: no cover
                print(f"[founders] LLM unavailable ({exc}); using synthetic profiles.")
                self._client = None

    def discover(self, company: Company, site_text: str = "") -> Company:
        # Prefer REAL officers/directors already extracted from the SEC filing.
        if any(f.get("source") == "sec_filing" for f in (company.founders or [])):
            return company
        if self._client is not None and site_text:
            founders = self._llm_extract(company, site_text)
            if founders:
                company.founders = founders
                return company
        company.founders = self._synthesize(company)
        return company

    # -- synthetic ----------------------------------------------------------
    def _synthesize(self, company: Company) -> list[dict]:
        r = _rng_ints(company.id, 12)
        n = 1 + (r[0] % 2)  # 1 or 2 founders
        slug = company.website or company.name.lower().replace(" ", "")
        domain = slug.replace("https://", "").replace("http://", "").strip("/")
        founders = []
        for i in range(n):
            first = FIRST[r[1 + i] % len(FIRST)]
            last = LAST[r[3 + i] % len(LAST)]
            role = ROLES[i if i < len(ROLES) else 0]
            tier = r[5 + i] % 3
            if tier == 2:
                bigco = BIGCOS[r[6 + i] % len(BIGCOS)]
                uni = UNIS[r[7 + i] % len(UNIS)]
                bg = f"Former senior researcher at {bigco}; PhD, {uni}."
                prev = [bigco]
                pedigree = 82 + (r[8 + i] % 14)
            elif tier == 1:
                su = STARTUPS[r[6 + i] % len(STARTUPS)]
                field = FIELDS[r[7 + i] % len(FIELDS)]
                bg = f"Early engineer at {su} (since acquired); background in {field}."
                prev = [su]
                pedigree = 64 + (r[8 + i] % 16)
            else:
                uni = UNIS[r[6 + i] % len(UNIS)]
                field = FIELDS[r[7 + i] % len(FIELDS)]
                bg = f"Second-time founder; {field} at {uni}."
                prev = ["(prior startup, undisclosed)"]
                pedigree = 50 + (r[8 + i] % 16)
            founders.append({
                "name": f"{first} {last}",
                "role": role,
                "background": bg,
                "previous_companies": prev,
                "profile_url": f"https://www.linkedin.com/search/results/people/?keywords={first}%20{last}%20{domain}",
                "pedigree": pedigree,
                "source": "synthetic",
            })
        return founders

    # -- llm ----------------------------------------------------------------
    def _llm_extract(self, company: Company, site_text: str) -> list[dict]:
        system = (
            "Extract founders/executives from the website text. Return STRICT JSON "
            '{"founders":[{"name","role","background","previous_companies":[],"profile_url"}]}. '
            "Only include people explicitly named in the text. If none, return an empty array."
        )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": f"Company: {company.name}\n\nText:\n{site_text[:3000]}"},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            out = data.get("founders", []) if isinstance(data, dict) else []
            for f in out:
                f["source"] = "llm (website extraction)"
                f.setdefault("pedigree", 60)
                f.setdefault("previous_companies", [])
            return out
        except Exception as exc:  # pragma: no cover
            print(f"[founders:llm] {company.name}: {exc}; falling back to synthetic.")
            return []

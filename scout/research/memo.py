"""Autonomous research agent (stretch goal 1).

Given a discovered company, this agent:
  * optionally visits the company website and extracts on-page signals,
  * estimates a market category and company stage,
  * drafts a one-page investment memo with explicit reasoning.

It is designed to *always produce a memo*. With no network and no LLM it runs a
fully deterministic heuristic; with a website it enriches from page text; with
`OPENAI_API_KEY` + `--llm` it upgrades the narrative to model-written prose.
This graceful degradation keeps the pipeline runnable anywhere.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional

from ..models import Company

DEFAULT_UA = "AI-Incorporation-Scout/0.1 (research-agent; contact: scout@example.com)"

# Coarse stage estimation from any capital / headcount signals we can find.
STAGE_HINTS: list[tuple[str, list[str]]] = [
    ("Series B+", ["series b", "series c", "series d", "growth round"]),
    ("Series A", ["series a"]),
    ("Seed", ["seed round", "pre-seed", "raised", "backed by", "led by"]),
]

# Indicative TAM framing per category (rough, investor-facing language only).
MARKET_NOTES: dict[str, str] = {
    "AI Infrastructure": "Picks-and-shovels layer for the AI build-out; large but capital-intensive and increasingly contested by incumbents.",
    "Developer Tools": "Bottoms-up developer adoption can compound fast, but monetization and platform risk (model vendors shipping native features) are key questions.",
    "AI Agents": "Early, fast-moving category; differentiation hinges on reliability, distribution, and a defensible workflow wedge.",
    "Computer Vision": "Mature ML discipline with deep verticals (industrial, medical, security); moats come from proprietary data and integrations.",
    "NLP / Language": "Directly exposed to frontier-model commoditization; winners own a domain, data loop, or distribution advantage.",
    "Robotics": "Hardware + AI; long capital cycles and real-world reliability bar, but durable moats once deployed.",
    "Healthcare AI": "Large regulated market; reimbursement, clinical validation, and data access gate the upside.",
    "Fintech AI": "High willingness-to-pay and clear ROI, offset by regulatory scrutiny and incumbent data advantages.",
    "Generative Media": "Consumer + creator demand is strong; retention and rights/IP risk are the open questions.",
    "Data / Analytics": "Durable enterprise budget line; differentiation requires going beyond dashboards into action.",
    "General AI": "Broad positioning; the memo flags a need to sharpen the wedge and ICP.",
}


class _TextExtractor(HTMLParser):
    """Minimal, dependency-free HTML -> text + meta-description extractor."""

    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.chunks: list[str] = []
        self.meta_description = ""
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "meta":
            a = dict(attrs)
            if a.get("name", "").lower() in ("description", "og:description") or a.get(
                "property", ""
            ).lower() == "og:description":
                self.meta_description = (a.get("content") or "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = text
        self.chunks.append(text)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.chunks)).strip()


@dataclass
class MemoAgent:
    """Produces structured investment memos for discovered companies."""

    use_llm: bool = False
    fetch_site: bool = True
    user_agent: str = DEFAULT_UA
    model: str = "gpt-4o-mini"
    timeout: int = 15

    def __post_init__(self) -> None:
        self._client = None
        self.last_site_text = ""  # exposes fetched page text for downstream agents
        if self.use_llm:
            try:
                from openai import OpenAI

                if not os.getenv("OPENAI_API_KEY"):
                    raise RuntimeError("OPENAI_API_KEY not set")
                self._client = OpenAI()
            except Exception as exc:  # pragma: no cover - depends on env
                print(f"[research] LLM unavailable ({exc}); using heuristic memos.")
                self._client = None

    # -- public API ---------------------------------------------------------
    def research(self, company: Company) -> Company:
        site = self._visit_site(company.website) if self.fetch_site else None
        self.last_site_text = (site or {}).get("text", "") if site else ""
        if site and site.get("meta_description") and not company.description:
            company.description = site["meta_description"][:500]

        if self._client is not None:
            memo = self._llm_memo(company, site)
        else:
            memo = self._heuristic_memo(company, site)
        company.memo = memo
        return company

    # -- website visit ------------------------------------------------------
    def _visit_site(self, url: Optional[str]) -> Optional[dict]:
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                html = resp.read(400_000).decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            return {"fetched": False, "error": str(exc)}
        parser = _TextExtractor()
        try:
            parser.feed(html)
        except Exception:
            pass
        return {
            "fetched": True,
            "title": parser.title,
            "meta_description": parser.meta_description,
            "text": parser.text()[:4000],
        }

    # -- heuristic memo -----------------------------------------------------
    def _heuristic_memo(self, company: Company, site: Optional[dict]) -> dict:
        corpus = " ".join(
            [
                company.name,
                company.description or "",
                (site or {}).get("text", "") if site else "",
            ]
        ).lower()

        category = company.ai_category or "General AI"
        # Prefer the real stage derived from the Form D capital signal.
        stage = (company.raw or {}).get("stage") or self._estimate_stage(corpus)
        market_note = MARKET_NOTES.get(category, MARKET_NOTES["General AI"])

        signals = list(company.ai_signals[:6])
        site_line = ""
        if site and site.get("fetched"):
            site_line = (
                f"Live site analyzed (title: \"{site.get('title') or 'n/a'}\")."
                if site.get("title")
                else "Live site analyzed."
            )
        elif site and not site.get("fetched"):
            site_line = "Website unreachable at research time; memo based on registry metadata."
        else:
            site_line = "No website on file yet (typical for very recently formed entities)."

        confidence_word = (
            "high" if company.ai_score >= 0.75 else "moderate" if company.ai_score >= 0.5 else "low"
        )

        thesis = (
            f"{company.name} surfaced via {company.source} as a newly formed entity"
            f"{(' in ' + company.jurisdiction) if company.jurisdiction else ''}. "
            f"Classifier confidence that it is AI-related is {confidence_word} "
            f"({company.ai_score:.0%}), best fitting the {category} category. {site_line}"
        )

        reasoning = (
            f"Category placement and stage are inferred from name, registry metadata, "
            f"and any on-page text. Signals: {', '.join(signals) if signals else 'none beyond name'}. "
            f"Market read: {market_note}"
        )

        risks = self._risks(category, company)

        return {
            "generated_by": "heuristic",
            "one_liner": self._one_liner(company, category),
            "market_category": category,
            "estimated_stage": stage,
            "thesis": thesis,
            "reasoning": reasoning,
            "market_note": market_note,
            "risks": risks,
            "signals": signals,
            "website_analyzed": bool(site and site.get("fetched")),
        }

    @staticmethod
    def _one_liner(company: Company, category: str) -> str:
        desc = (company.description or "").strip()
        if desc:
            first = re.split(r"(?<=[.!?])\s", desc)[0]
            return first[:160]
        return f"Newly formed {category} company discovered pre-database."

    @staticmethod
    def _estimate_stage(corpus: str) -> str:
        for stage, hints in STAGE_HINTS:
            if any(h in corpus for h in hints):
                return stage
        return "Pre-seed / Formation"

    @staticmethod
    def _risks(category: str, company: Company) -> list[str]:
        risks = []
        if company.ai_score < 0.6:
            risks.append("AI-relevance is uncertain; may be buzzword-only positioning.")
        if not company.website:
            risks.append("No discoverable web presence yet; hard to verify traction.")
        if category in ("NLP / Language", "Generative Media"):
            risks.append("Exposed to frontier-model commoditization and platform risk.")
        if category == "Robotics":
            risks.append("Hardware capital intensity and long deployment cycles.")
        if category in ("Healthcare AI", "Fintech AI"):
            risks.append("Regulatory and compliance overhead can slow go-to-market.")
        if not risks:
            risks.append("Standard early-stage execution and distribution risk.")
        return risks

    # -- llm memo -----------------------------------------------------------
    def _llm_memo(self, company: Company, site: Optional[dict]) -> dict:
        system = (
            "You are a venture analyst writing a concise one-page investment memo on a "
            "newly formed company. Be specific and skeptical. Return STRICT JSON with keys: "
            "one_liner, market_category, estimated_stage, thesis, reasoning, market_note, "
            "risks (array of strings)."
        )
        user = (
            f"Name: {company.name}\n"
            f"Jurisdiction: {company.jurisdiction or 'n/a'}\n"
            f"Website: {company.website or 'n/a'}\n"
            f"Registry description: {company.description or 'n/a'}\n"
            f"AI classifier score: {company.ai_score:.2f} ({company.ai_category or 'n/a'})\n"
            f"On-page text (truncated): {(site or {}).get('text', 'n/a')[:1500]}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            data.setdefault("market_category", company.ai_category or "General AI")
            data.setdefault("estimated_stage", "Pre-seed / Formation")
            if isinstance(data.get("risks"), str):
                data["risks"] = [data["risks"]]
            data["generated_by"] = "llm"
            data["signals"] = list(company.ai_signals[:6])
            data["website_analyzed"] = bool(site and site.get("fetched"))
            return data
        except Exception as exc:  # pragma: no cover - network/env dependent
            print(f"[research:llm] {company.name}: {exc}; falling back to heuristic memo.")
            return self._heuristic_memo(company, site)

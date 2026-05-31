"""Venture Analyst Swarm orchestration (stretch goal 3).

A pipeline of cooperating, specialized agents turns a raw public record into an
investor-ready recommendation:

    Discovery  → source connectors yield newly formed companies
    Classifier → AI-relatedness score + subsector
    Research   → visits the site, drafts an investment memo
    Founder    → structured founder/executive profiles
    Scoring    → 6-dimension opportunity score + confidence
    Market     → competitive landscape (leaders, peers, white space)
    Reporting  → synthesizes everything into a final recommendation

Each stage is independent and fail-soft: a bad record or flaky network degrades
that one item rather than aborting the run — essential for an unattended agent.
The deeper-analysis agents only run on companies above a confidence threshold,
which keeps cost focused on the most promising discoveries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .classify import get_classifier
from .competitive import MarketAgent
from .db import Database
from .founders import FounderAgent
from .models import Company
from .recommend import ReportingAgent
from .score import ScoringAgent
from .validate import verify_company
from .sources import get_source


@dataclass
class RunReport:
    source: str
    fetched: int = 0
    classified_ai: int = 0
    analyzed: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"[{self.source}] fetched={self.fetched} ai={self.classified_ai} "
            f"analyzed={self.analyzed} inserted={self.inserted} "
            f"updated={self.updated} errors={len(self.errors)}"
        )


@dataclass
class Pipeline:
    db: Database
    use_llm: bool = False
    research: bool = False           # run the full analyst swarm
    research_min_score: float = 0.5
    fetch_site: bool = True
    classifier_kwargs: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._classifier = get_classifier(use_llm=self.use_llm, **self.classifier_kwargs)
        self._memo = None
        self._founder = None
        self._scorer = None
        self._market = None
        self._reporter = None
        if self.research:
            from .research import MemoAgent

            self._memo = MemoAgent(use_llm=self.use_llm, fetch_site=self.fetch_site)
            self._founder = FounderAgent(use_llm=self.use_llm)
            self._scorer = ScoringAgent()
            self._market = MarketAgent()
            self._reporter = ReportingAgent()

    def run(self, source_name: str, limit: int = 100, **source_kwargs) -> RunReport:
        report = RunReport(source=source_name)
        source = get_source(source_name, **source_kwargs)

        # Pass 1 — discover + classify.
        batch: list[Company] = []
        for company in source.fetch(limit=limit):
            report.fetched += 1
            try:
                verify_company(company)
                self._classifier.classify(company)
                if company.is_ai:
                    report.classified_ai += 1
            except Exception as exc:
                report.errors.append(f"classify {company.name}: {exc}")
            batch.append(company)

        # Pass 2 — deep analysis swarm (only for promising companies).
        if self.research:
            # Market agent needs the whole batch (plus prior DB rows) for adjacency.
            known = self.db.all(ai_only=True)
            self._market.index(known + batch)
            for company in batch:
                if company.ai_score < self.research_min_score:
                    continue
                try:
                    self._memo.research(company)
                    self._founder.discover(company, site_text=self._memo.last_site_text)
                    self._scorer.score(company)             # uses founders
                    self._market.analyze(company)
                    self._reporter.report(company)          # uses scores + market + founders
                    report.analyzed += 1
                except Exception as exc:
                    report.errors.append(f"analyze {company.name}: {exc}")

        inserted, updated = self.db.upsert_many(batch)
        report.inserted, report.updated = inserted, updated
        return report

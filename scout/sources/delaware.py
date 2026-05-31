"""Reliable Delaware incorporation source (EDGAR-backed).

Delaware's own ICIS portal has no bulk API and discourages scraping, so for a
robust, *legitimate* feed of newly formed Delaware firms we use SEC EDGAR's
state-of-incorporation filter: Form D filers whose `inc_state == DE`. These are
real entities incorporated in Delaware, each with a verifiable SEC CIK and a
public filing — discoverable months before they hit mainstream databases.

Free, official, no API key, no anti-bot fight. `days_back` controls the window
so we catch firms in their first weeks of activity.
"""

from __future__ import annotations

from typing import Iterator

from ..models import Company
from .base import Source
from .sec_edgar import SecEdgarSource


class DelawareSource(Source):
    name = "delaware"

    def __init__(
        self,
        days_back: int = 45,
        query: str = "",
        forms: str = "D",
        user_agent: str = "",
        request_delay: float = 0.2,
        # Accept --max-age-days as an alias so the CLI flag works for both
        # the EDGAR-backed and ICIS sources.
        max_age_days: int | None = None,
        **_: object,
    ) -> None:
        if max_age_days is not None:
            days_back = max_age_days
        kwargs: dict = {
            "inc_state": "DE",
            "days_back": days_back,
            "query": query,
            "forms": forms,
            "request_delay": request_delay,
        }
        if user_agent:
            kwargs["user_agent"] = user_agent
        self._edgar = SecEdgarSource(**kwargs)

    def fetch(self, limit: int = 100) -> Iterator[Company]:
        for company in self._edgar.fetch(limit=limit):
            company.source = self.name
            yield company

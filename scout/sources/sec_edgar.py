"""SEC EDGAR connector (live public source).

Companies filing a **Form D** (Notice of Exempt Offering of Securities) are
typically recently formed entities raising their first private capital -- an
excellent leading signal for "newly formed company" discovery, often months
before they appear in mainstream startup databases.

This connector queries EDGAR full-text search, which is free and requires only
a descriptive User-Agent header (per SEC's fair-access policy). It degrades
gracefully: network errors are logged and yield nothing rather than crashing
the pipeline.

Docs: https://www.sec.gov/os/webmaster-faq#developers
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Iterator

from ..models import Company
from .base import Source

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
# SEC requires a User-Agent identifying the requester. Override via constructor.
DEFAULT_UA = "AI-Incorporation-Scout/1.0 (contact: scout@example.com)"

# US state code -> full name, for human-readable jurisdictions.
STATE_NAMES = {
    "DE": "Delaware", "CA": "California", "NY": "New York", "TX": "Texas",
    "MA": "Massachusetts", "WA": "Washington", "FL": "Florida", "IL": "Illinois",
    "CO": "Colorado", "NV": "Nevada", "NJ": "New Jersey", "PA": "Pennsylvania",
    "GA": "Georgia", "VA": "Virginia", "NC": "North Carolina", "WY": "Wyoming",
}


class SecEdgarSource(Source):
    """Live SEC EDGAR connector.

    Form D filers are recently formed entities raising first private capital.
    With `inc_state` set (e.g. "DE"), EDGAR's `locationType=incorporated` filter
    returns only companies *incorporated in that state* — a legitimate, free,
    official way to discover newly formed Delaware firms with a verifiable CIK.
    """

    name = "sec_edgar"

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        forms: str = "D",
        days_back: int = 30,
        query: str = "",
        inc_state: str = "",          # state of incorporation filter, e.g. "DE"
        request_delay: float = 0.2,
        **_: object,
    ) -> None:
        self.user_agent = user_agent
        self.forms = forms
        self.days_back = days_back
        self.query = query  # optional full-text query to bias toward AI filings
        self.inc_state = (inc_state or "").upper()
        self.request_delay = request_delay

    def _get(self, params: dict) -> dict:
        url = f"{EFTS_URL}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch(self, limit: int = 100) -> Iterator[Company]:
        end = date.today()
        start = end - timedelta(days=self.days_back)
        fetched = 0
        page_from = 0
        page_size = 100

        while fetched < limit:
            params = {
                "q": self.query or '"securities"',
                "forms": self.forms,
                "startdt": start.isoformat(),
                "enddt": end.isoformat(),
                "from": page_from,
            }
            if self.inc_state:
                params["locationCodes"] = self.inc_state
                params["locationType"] = "incorporated"
            try:
                data = self._get(params)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"[sec_edgar] request failed ({exc}); stopping early.")
                return

            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                return

            for hit in hits:
                if fetched >= limit:
                    return
                company = self._hit_to_company(hit)
                if company:
                    fetched += 1
                    yield company

            page_from += page_size
            time.sleep(self.request_delay)

    @staticmethod
    def _jurisdiction(inc_states: list[str], biz_states: list[str]) -> str:
        # Prefer state of incorporation; fall back to business address state.
        code = (inc_states or biz_states or [""])[0]
        full = STATE_NAMES.get(code, code)
        return f"{full}, USA" if full else "USA"

    @staticmethod
    def _hit_to_company(hit: dict) -> Company | None:
        src = hit.get("_source", {})
        names = src.get("display_names") or []
        if not names:
            return None
        # display_names look like "ACME AI INC.  (CIK 0001234567)"
        raw_name = names[0]
        name = re.sub(r"\s*\(CIK[^)]*\)\s*$", "", raw_name).strip()
        cik_match = re.search(r"CIK\s*(\d+)", raw_name)
        cik = cik_match.group(1) if cik_match else ""
        file_date = src.get("file_date")  # proxy for formation/discovery
        accession = hit.get("_id", "")
        form = src.get("file_type") or "D"  # this is a string, e.g. "D" or "D/A"
        inc_states = src.get("inc_states") or []
        biz_states = src.get("biz_states") or []

        inc_full = STATE_NAMES.get((inc_states or [""])[0], (inc_states or [""])[0])
        where = f" incorporated in {inc_full}" if inc_full else ""

        # A CIK is a stable SEC identifier whose filing is publicly verifiable.
        edgar_filing = (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=D"
            if cik else None
        )

        return Company(
            name=name,
            source=SecEdgarSource.name,
            source_id=cik or accession,
            jurisdiction=SecEdgarSource._jurisdiction(inc_states, biz_states),
            formation_date=file_date,
            website=None,
            description=f"Form {form} filer on SEC EDGAR{where} (new exempt securities offering).",
            raw={
                "cik": cik,
                "accession": accession,
                "file_date": file_date,
                "file_type": form,
                "inc_states": inc_states,
                "biz_states": biz_states,
                "edgar_url": edgar_filing,
                "registry": "SEC EDGAR",
            },
        )

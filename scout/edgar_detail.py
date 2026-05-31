"""Enrich a Form D filing with its real, public details.

EDGAR's Form D primary document (`primary_doc.xml`) contains structured, *real*
data we can attribute with confidence:

  * **related persons** — executive officers, directors, promoters (real names),
    with city/state. These are the actual people behind the company.
  * **industry group** — lets us distinguish operating companies from pooled
    investment funds / SPVs.
  * **offering amount / amount sold** — a real capital signal we map to a stage.

This is all fail-soft: any network or parse error returns ``None`` so the
pipeline degrades gracefully rather than crashing.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

DEFAULT_UA = "AI-Incorporation-Scout/1.0 (contact: scout@example.com)"

_ENTITY_SUFFIXES = ("LLC", "L.L.C", "INC", "L.P", "LP", "LTD", "CORP", "TRUST", "FUND", "PARTNERS", "MANAGEMENT")


def _tag(blk: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", blk, re.S)
    return (m.group(1).strip() if m else "")


def _doc_url(cik: str, accession: str) -> str:
    acc = accession.split(":")[0]
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/primary_doc.xml"


def _is_person(first: str, last: str) -> bool:
    """Filter out entity 'officers' (LLCs/LPs) and blanks."""
    if not first or first.upper() in {"N/A", "NA", "NONE"}:
        return False
    blob = f"{first} {last}".upper()
    return not any(re.search(rf"(?<![A-Z]){s}(?![A-Z])", blob) for s in _ENTITY_SUFFIXES)


def _money(raw: str) -> Optional[int]:
    if not raw or not raw.isdigit():
        return None
    return int(raw)


def estimate_stage(offering: Optional[int], sold: Optional[int]) -> str:
    amt = sold if (sold and sold > 0) else offering
    if amt is None:
        return "Stealth / Pre-seed"
    if amt <= 2_000_000:
        return "Pre-seed"
    if amt <= 6_000_000:
        return "Seed"
    if amt <= 20_000_000:
        return "Series A"
    if amt <= 75_000_000:
        return "Series B"
    return "Growth"


def _linkedin(name: str, company: str) -> str:
    # A LinkedIn people-search link is honest: it resolves to the real person's
    # profile rather than fabricating a URL.
    q = urllib.parse.quote(f"{name} {company}".strip())
    return f"https://www.linkedin.com/search/results/people/?keywords={q}"


def fetch_form_d_detail(
    cik: str,
    accession: str,
    company_name: str = "",
    user_agent: str = DEFAULT_UA,
    timeout: int = 25,
) -> Optional[dict]:
    if not cik or not accession:
        return None
    url = _doc_url(cik, accession)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            xml = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None

    industry = _tag(xml, "industryGroupType")
    offering = _money(_tag(xml, "totalOfferingAmount"))
    sold = _money(_tag(xml, "totalAmountSold"))
    revenue = _tag(xml, "revenueRange")

    people: list[dict] = []
    for m in re.finditer(r"<relatedPersonInfo>(.*?)</relatedPersonInfo>", xml, re.S):
        blk = m.group(1)
        first, last = _tag(blk, "firstName"), _tag(blk, "lastName")
        if not _is_person(first, last):
            continue
        rels = re.findall(r"<relationship>(.*?)</relationship>", blk, re.S)
        city, state = _tag(blk, "city"), _tag(blk, "stateOrCountry")
        loc = ", ".join([p for p in (city, state) if p and p != "N/A"])
        name = f"{first} {last}".strip()
        people.append({
            "name": name,
            "role": ", ".join(r.strip() for r in rels) or "Officer",
            "location": loc,
            "linkedin": _linkedin(name, company_name),
            "source": "sec_filing",
        })

    return {
        "industry_group": industry,
        "is_fund": "Pooled Investment Fund" in industry,
        "offering_amount": offering,
        "amount_sold": sold,
        "revenue_range": revenue if revenue and revenue != "Decline to Disclose" else "",
        "stage": estimate_stage(offering, sold),
        "related_persons": people,
        "filing_url": url,
    }

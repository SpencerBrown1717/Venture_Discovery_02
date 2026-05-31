"""Delaware Division of Corporations scraper (ICIS public entity search).

NOTE: This is a *best-effort* connector. The official ICIS portal explicitly
discourages automated data mining and is anti-automation: it frequently returns
transient errors under programmatic access. For a reliable Delaware feed, prefer
the `delaware` source (EDGAR state-of-incorporation filter). This connector is
kept for completeness / manual use where the portal cooperates.

It politely queries the ICIS name-search portal, pulls entity file numbers and
names, fetches each entity's detail page for the incorporation date, and keeps
only entities formed within the scout window (default: last 30 days), with
retries/backoff and fail-soft behavior.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from http.cookiejar import CookieJar
from typing import Iterator

from ..models import Company
from .base import Source

SEARCH_URL = "https://icis.corp.delaware.gov/ecorp/entitysearch/namesearch.aspx"
DEFAULT_UA = (
    "AI-Incorporation-Scout/1.0 "
    "(Delaware public registry research; contact: scout@example.com)"
)

# Keywords biased toward AI-related newly formed entity names.
DEFAULT_KEYWORDS = [
    "ARTIFICIAL",
    "AGENT",
    "AGENTIC",
    "NEURAL",
    "ROBOT",
    "VISION",
    "COGNITIVE",
    "INFERENCE",
    "GENERATIVE",
    "LLM",
    "MACHINE LEARNING",
    "DEEP LEARNING",
]

INPUT_RE = re.compile(r"<input([^>]+)>", re.I)
NAME_RE = re.compile(r'name="([^"]+)"', re.I)
VALUE_RE = re.compile(r'value="([^"]*)"', re.I)
TYPE_RE = re.compile(r'type="([^"]+)"', re.I)

# Detail page: "INCORPORATION DATE:" … value cell
INC_DATE_RE = re.compile(
    r"INCORPORATION\s+DATE\s*:?\s*</[^>]+>\s*</td>\s*<td[^>]*>\s*([^<]+)",
    re.I | re.S,
)
# Alternate label used on some entity types
FORM_DATE_RE = re.compile(
    r"FORMATION\s+DATE\s*:?\s*</[^>]+>\s*</td>\s*<td[^>]*>\s*([^<]+)",
    re.I | re.S,
)
# Grid row: file number + entity link with __doPostBack target
ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*"
    r"(?:<a[^>]*__doPostBack\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]*)['\"]\)"
    r"[^>]*>)?\s*([^<]+?)\s*(?:</a>)?\s*</td>",
    re.I | re.S,
)


def _parse_hidden(html: str) -> dict[str, str]:
    """Only the ASP.NET hidden state fields (__VIEWSTATE, __EVENTVALIDATION, …).

    The ICIS portal rejects requests that echo back extra form inputs (notably
    the `email_confirm` honeypot and the postback-source hidden field), so we
    deliberately keep the payload minimal to match the known-good recipe.
    """
    fields: dict[str, str] = {}
    for m in re.finditer(
        r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*?(?:value="([^"]*)")?[^>]*>',
        html,
        re.I,
    ):
        name, value = m.group(1), m.group(2) or ""
        if name.startswith("__"):
            fields[name] = value
    return fields


def _parse_all_hidden(html: str) -> dict[str, str]:
    """All hidden fields (needed to drive a detail postback)."""
    fields: dict[str, str] = {}
    for m in re.finditer(r"<input([^>]+)>", html, re.I):
        tag = m.group(1)
        if "hidden" not in tag.lower():
            continue
        nm = NAME_RE.search(tag)
        if not nm:
            continue
        val = VALUE_RE.search(tag)
        fields[nm.group(1)] = val.group(1) if val else ""
    return fields


def _strip_html(html: str) -> list[str]:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _parse_search_rows(html: str) -> list[tuple[str, str, str, str]]:
    """Return (file_number, event_target, event_arg, entity_name)."""
    rows: list[tuple[str, str, str, str]] = []
    for m in ROW_RE.finditer(html):
        file_num, target, arg, name = m.group(1), m.group(2) or "", m.group(3) or "", m.group(4).strip()
        if file_num.isdigit() and name:
            rows.append((file_num, target, arg, name))

    if rows:
        return rows

    # Fallback: plain FILE NUMBER / ENTITY NAME text pairs (no postback).
    lines = _strip_html(html)
    if "FILE NUMBER" not in lines:
        return rows
    i = lines.index("FILE NUMBER")
    chunk = lines[i + 2 : i + 200]
    for j in range(0, len(chunk) - 1, 2):
        if chunk[j].isdigit():
            rows.append((chunk[j], "", "", chunk[j + 1]))
    return rows


def _parse_inc_date(html: str) -> str | None:
    for pat in (INC_DATE_RE, FORM_DATE_RE):
        m = pat.search(html)
        if m:
            return m.group(1).strip()
    # Last resort: look for MM/DD/YYYY near "INCORPORATION"
    lines = _strip_html(html)
    for i, ln in enumerate(lines):
        if "INCORPORATION DATE" in ln.upper() and i + 1 < len(lines):
            candidate = lines[i + 1]
            if re.match(r"\d{1,2}/\d{1,2}/\d{4}", candidate):
                return candidate
    return None


def _to_iso(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


class DelawareIcisSource(Source):
    name = "delaware_icis"

    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        keywords: list[str] | None = None,
        max_age_days: int = 30,
        request_delay: float = 1.5,
        timeout: int = 45,
        **_: object,
    ) -> None:
        self.user_agent = user_agent
        self.keywords = keywords or list(DEFAULT_KEYWORDS)
        self.max_age_days = max_age_days
        self.request_delay = request_delay
        self.timeout = timeout
        self._jar = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))
        self._last_html = ""

    def _fetch(self, url: str, data: bytes | None = None) -> str:
        headers = {
            "User-Agent": self.user_agent,
            "Referer": SEARCH_URL,
            "Accept": "text/html,application/xhtml+xml",
        }
        req = urllib.request.Request(url, data=data, headers=headers)
        if data is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with self._opener.open(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _sleep(self) -> None:
        time.sleep(self.request_delay)

    def _post_minimal(self, extra: dict[str, str], retries: int = 3) -> str:
        """Submit a minimal payload (hidden __ fields + extra), with backoff.

        A fresh GET (new ASP.NET state) precedes each attempt; the portal is
        flaky and intermittently returns "An error occurred" on valid input.
        """
        last = ""
        for attempt in range(retries):
            try:
                page = self._fetch(SEARCH_URL)
                fields = _parse_hidden(page)
                fields.update(extra)
                body = urllib.parse.urlencode(fields).encode("utf-8")
                self._sleep()
                last = self._fetch(SEARCH_URL, body)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = ""
                print(f"[delaware] request error ({exc}); retrying.")
            if last and "An error occurred" not in last:
                return last
            time.sleep(self.request_delay * (attempt + 2))  # backoff
        return last

    def _search(self, term: str) -> str:
        self._last_html = self._post_minimal({
            "ctl00$ContentPlaceHolder1$frmEntityName": term,
            "ctl00$ContentPlaceHolder1$btnSubmit": "Search",
        })
        return self._last_html

    def _detail_via_postback(self, event_target: str, event_arg: str) -> str:
        fields = _parse_all_hidden(self._last_html)
        fields["__EVENTTARGET"] = event_target
        fields["__EVENTARGUMENT"] = event_arg
        body = urllib.parse.urlencode(fields).encode("utf-8")
        self._sleep()
        try:
            return self._fetch(SEARCH_URL, body)
        except (urllib.error.URLError, TimeoutError, OSError):
            return ""

    def _detail_via_file_number(self, file_number: str) -> str:
        return self._post_minimal({
            "ctl00$ContentPlaceHolder1$frmFileNumber": file_number,
            "ctl00$ContentPlaceHolder1$btnSubmit": "Search",
        })

    def _within_window(self, formation_iso: str | None) -> bool:
        if not formation_iso:
            return False
        try:
            formed = date.fromisoformat(formation_iso)
        except ValueError:
            return False
        cutoff = date.today() - timedelta(days=self.max_age_days)
        return formed >= cutoff

    def fetch(self, limit: int = 100) -> Iterator[Company]:
        cutoff = date.today() - timedelta(days=self.max_age_days)
        seen: set[str] = set()
        yielded = 0

        for kw in self.keywords:
            if yielded >= limit:
                return
            try:
                html = self._search(kw)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                print(f"[delaware] search '{kw}' failed ({exc}); skipping.")
                continue

            if "An error occurred" in html:
                print(f"[delaware] search '{kw}' returned portal error; skipping.")
                continue

            rows = _parse_search_rows(html)
            print(f"[delaware] '{kw}' -> {len(rows)} entities")

            for file_num, target, arg, entity_name in rows:
                if yielded >= limit or file_num in seen:
                    continue
                seen.add(file_num)

                try:
                    if target:
                        detail_html = self._detail_via_postback(target, arg)
                    else:
                        detail_html = self._detail_via_file_number(file_num)
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    print(f"[delaware] detail {file_num} failed ({exc}); skipping.")
                    continue

                if "An error occurred" in detail_html and not _parse_inc_date(detail_html):
                    print(f"[delaware] detail {file_num} portal error; skipping.")
                    continue

                formation_iso = _to_iso(_parse_inc_date(detail_html))
                if not self._within_window(formation_iso):
                    continue

                agent = ""
                agent_m = re.search(
                    r"REGISTERED\s+AGENT\s*(?:INFORMATION)?[^<]*</[^>]+>\s*</td>\s*<td[^>]*>\s*([^<]+)",
                    detail_html,
                    re.I | re.S,
                )
                if agent_m:
                    agent = re.sub(r"\s+", " ", agent_m.group(1)).strip()

                yield Company(
                    name=entity_name,
                    source=self.name,
                    source_id=file_num,
                    jurisdiction="Delaware, USA",
                    formation_date=formation_iso,
                    description=(
                        f"Delaware {self._entity_kind(detail_html)} "
                        f"(file #{file_num}). Registered agent: {agent or 'on file'}."
                    ),
                    website=None,
                    raw={
                        "file_number": file_num,
                        "keyword": kw,
                        "registered_agent": agent,
                        "incorporation_date_raw": _parse_inc_date(detail_html),
                        "registry_url": SEARCH_URL,
                        "scout_window_days": self.max_age_days,
                        "cutoff_date": cutoff.isoformat(),
                    },
                )
                yielded += 1

    @staticmethod
    def _entity_kind(html: str) -> str:
        m = re.search(
            r"ENTITY\s+KIND\s*:?\s*</[^>]+>\s*</td>\s*<td[^>]*>\s*([^<]+)",
            html,
            re.I | re.S,
        )
        return m.group(1).strip() if m else "entity"

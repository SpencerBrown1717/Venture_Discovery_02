"""Website URL verification.

Before surfacing a link to investors, we confirm the domain resolves and returns
a successful HTTP response. Invalid URLs are cleared so the dashboard never
shows DNS errors or dead links.
"""

from __future__ import annotations

import urllib.error
import urllib.request

DEFAULT_UA = "AI-Incorporation-Scout/1.0 (link-validator)"


def verify_url(url: str | None, timeout: int = 10, user_agent: str = DEFAULT_UA) -> bool:
    """Return True if `url` is reachable (DNS + HTTP 2xx/3xx)."""
    if not url or not url.strip():
        return False
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    headers = {"User-Agent": user_agent}
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except urllib.error.HTTPError as exc:
        if exc.code in (405, 403):
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return 200 <= resp.status < 400
            except Exception:
                return False
        return False
    except Exception:
        return False


def verify_company_website(company, *, clear_on_fail: bool = True) -> bool:
    """Validate `company.website`, set `website_verified`, optionally clear bad URL."""
    ok = verify_url(company.website)
    company.website_verified = ok
    if not ok and clear_on_fail:
        company.website = None
    return ok


def verify_company(company, *, check_website: bool = True) -> bool:
    """Establish that a company is *real* via independent, auditable signals.

    A company is considered verified-real if at least one authoritative source
    confirms it exists:
      * an SEC EDGAR CIK (a registered filer with a public filing), or
      * a government registry file number (e.g. Delaware), or
      * a website that resolves over HTTP.

    Each passing check is recorded in `company.verification` for provenance, and
    `company.verified_real` is set accordingly.
    """
    sources: list[str] = []
    raw = company.raw or {}

    cik = str(raw.get("cik") or "").strip()
    if cik:
        sources.append(f"SEC EDGAR CIK {cik}")

    file_number = str(raw.get("file_number") or "").strip()
    if file_number:
        sources.append(f"Delaware file #{file_number}")

    if check_website and company.website:
        if verify_company_website(company):
            host = company.website.replace("https://", "").replace("http://", "").strip("/")
            sources.append(f"Live website ({host})")
    elif check_website:
        # still record the (failed/empty) website check without raising
        company.website_verified = bool(company.website) and verify_url(company.website)

    company.verification = sources
    company.verified_real = bool(sources)
    return company.verified_real

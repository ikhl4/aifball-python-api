"""Read-only live evidence fetcher for curated official football sources.

Returns source text excerpts, NOT verified match facts. Never follows arbitrary
user-supplied URLs. This endpoint is intentionally limited to official sources.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
import re
import requests
from fastapi import APIRouter, HTTPException, Query
from global_source_router import REGISTRY, GLOBAL, CONFEDERATIONS

router = APIRouter(prefix="/research/live", tags=["live-official-evidence"])

OFFICIAL_URLS = {
    url for country in REGISTRY.values() for entries in country.values()
    for _, url in entries
} | {url for _, url in GLOBAL} | {url for _, url in CONFEDERATIONS.values()}
# Explicit first-team pages, not inferred from home pages.
CLUB_PAGES = {
    "barcelona": ("FC Barcelona first-team results", "https://www.fcbarcelona.com/en/football/first-team/results", "first_team"),
    "برشلونة": ("FC Barcelona first-team results", "https://www.fcbarcelona.com/en/football/first-team/results", "first_team"),
    "al hilal": ("Al Hilal men's first-team fixtures", "https://alhilal.com/en/matches/mens-team/fixtures/saudi-arabian-league", "first_team"),
    "الهلال": ("Al Hilal men's first-team fixtures", "https://alhilal.com/ar/matches/mens-team/fixtures", "first_team"),
}
ALLOWED = OFFICIAL_URLS | {v[1] for v in CLUB_PAGES.values()}
MAX_BYTES = 500_000

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = 0
        self.focus = 0
        self.focus_parts = []
        self._stack = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._stack.append((tag, bool(tag in ("main", "article") or attrs.get("role") == "main")))
        if self._stack[-1][1]:
            self.focus += 1
        if tag in ("script", "style", "noscript", "svg", "nav", "footer", "header"):
            self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "nav", "footer", "header") and self.skip:
            self.skip -= 1
        if self._stack and self._stack[-1][0] == tag:
            _, focused = self._stack.pop()
            if focused:
                self.focus -= 1
    def handle_data(self, data):
        if not self.skip and data.strip():
            value = data.strip()
            self.parts.append(value)
            if self.focus:
                self.focus_parts.append(value)

def fetch_official(url: str):
    if url not in ALLOWED or urlparse(url).scheme != "https":
        raise HTTPException(400, "URL is not in the official source allowlist")
    try:
        # Disable redirects to avoid jumping to an unapproved host.
        with requests.get(url, timeout=(4, 10), allow_redirects=False,
                          headers={"User-Agent": "AiFBallResearch/1.0 (source verification)"}, stream=True) as response:
            if 300 <= response.status_code < 400:
                return {"status": "redirect_not_followed", "http_status": response.status_code}
            response.raise_for_status()
            if "text/html" not in response.headers.get("Content-Type", "").lower():
                return {"status": "unsupported_content_type"}
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    return {"status": "page_too_large"}
            # requests apparent_encoding can misread Arabic; prefer declared charset or UTF-8.
            encoding = response.encoding if response.encoding and response.encoding.lower() not in ("iso-8859-1", "latin-1") else "utf-8"
            page = bytes(raw).decode(encoding, errors="replace")
            parser = VisibleText()
            parser.feed(page)
            focused = parser.focus_parts or parser.parts
            excerpt = " ".join(focused)
            excerpt = re.sub(r"\\s+", " ", excerpt).strip()
            # The source can be live while containing no machine-verifiable fixture.
            return {"status": "ok", "text": excerpt[:12000],
                    "extraction_scope": "main_content" if parser.focus_parts else "page_fallback",
                    "match_facts": [], "match_facts_status": "not_extracted"}
    except requests.RequestException as exc:
        return {"status": "fetch_failed", "error_type": type(exc).__name__}

@router.get("/club")
def club_evidence(club: str = Query(min_length=2, max_length=100)):
    key = club.strip().casefold()
    if key not in CLUB_PAGES:
        return {"club": club, "status": "not_configured", "verified_live": False,
                "note": "No vetted club-specific first-team page configured."}
    title, url, squad = CLUB_PAGES[key]
    result = fetch_official(url)
    return {"club": club, "source_title": title, "source_url": url, "squad": squad,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fetch": result, "verified_live": False,
            "note": "Raw page evidence only. Match facts require structured extraction and cross-checking."}

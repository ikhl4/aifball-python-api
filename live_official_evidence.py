"""Read-only live evidence fetcher for curated official football sources.

Returns source text excerpts, NOT verified match facts. Never follows arbitrary
user-supplied URLs. This endpoint is intentionally limited to official sources.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
import re
import os
import json
import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, JSONResponse
from global_source_router import REGISTRY, GLOBAL, CONFEDERATIONS
from official_match_extractor import extract_barcelona_results, clean_encoding

router = APIRouter(prefix="/research/live", tags=["live-official-evidence"])

# ASCII-only explicit substitutions, independent of source-file encoding.
# Limit to observed corrupted names; this is a guard, not a general codec fix.
KNOWN_REPAIRS = {
    "Atl\\u00c3\\u00a9tico": "Atl\\u00e9tico",
    "Alav\\u00c3\\u00a9s": "Alav\\u00e9s",
    "Ram\\u00c3\\u00b3n": "Ram\\u00f3n",
    "S\\u00c3\\u00a1nchez": "S\\u00e1nchez",
    "Pizju\\u00c3\\u00a1n": "Pizju\\u00e1n",
    "Mart\\u00c3\\u00adnez": "Mart\\u00ednez",
}

def normalize_output(value):
    if isinstance(value, str):
        value = clean_encoding(value)
        for bad, good in KNOWN_REPAIRS.items():
            value = value.replace(bad, good)
        return value
    if isinstance(value, list):
        return [normalize_output(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize_output(item) for key, item in value.items()}
    return value


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
            # Official HTML may contain mojibake even when the declared charset decodes.
            # Normalize known sequences before visible-text extraction and JSON output.
            page = clean_encoding(page)
            parser = VisibleText()
            parser.feed(page)
            focused = parser.focus_parts or parser.parts
            excerpt = clean_encoding(" ".join(focused))
            excerpt = re.sub(r"\s+", " ", excerpt).strip()
            # The source can be live while containing no machine-verifiable fixture.
            return {"status": "ok", "text": excerpt[:12000],
                    "extraction_scope": "main_content" if parser.focus_parts else "page_fallback",
                    "match_facts": [], "match_facts_status": "not_extracted"}
    except requests.RequestException as exc:
        return {"status": "fetch_failed", "error_type": type(exc).__name__}

# Independent-source evidence is deliberately explicit and auditable.
# Do not infer verification from the club's own results page.
INDEPENDENT_MATCH_EVIDENCE = {
    ("2026-11-08", "La Liga", "Atlético Madrid", "FC Barcelona", 1, 2): {
        "source": "LaLiga",
        "url": "https://iaas-public-front-pro.laliga.com/en-US/match/temporada-2026-2027-laliga-ea-sports-atletico-de-madrid-fc-barcelona-12",
    },
}

def attach_independent_verification(matches):
    verified = 0
    for match in matches:
        match["verification"] = "extracted_unverified"
        match.pop("verification_evidence", None)
        key = (match.get("date"), match.get("competition"),
               clean_encoding(match.get("home_team", "")),
               clean_encoding(match.get("away_team", "")),
               match.get("home_score"), match.get("away_score"))
        evidence = INDEPENDENT_MATCH_EVIDENCE.get(key)
        if evidence:
            match["verification"] = "verified_independent"
            match["verification_evidence"] = evidence
            verified += 1
    return verified


@router.get("/club")
def club_evidence(club: str = Query(min_length=2, max_length=100)):
    key = club.strip().casefold()
    if key not in CLUB_PAGES:
        return {"club": club, "status": "not_configured", "verified_live": False,
                "note": "No vetted club-specific first-team page configured."}
    title, url, squad = CLUB_PAGES[key]
    result = fetch_official(url)
    if result.get("status") == "ok" and key in ("barcelona", "برشلونة"):
        candidates = extract_barcelona_results(result.get("text", ""), url, squad)
        result["match_facts"] = candidates
        verified_count = attach_independent_verification(candidates)
        result["match_facts_status"] = "partially_verified" if verified_count else ("extracted_unverified" if candidates else "not_extracted")
        result["verification_summary"] = {"verified_independent": verified_count,
                                          "extracted_unverified": len(candidates) - verified_count,
                                          "total": len(candidates)}
    # Final boundary normalization: the upstream HTML sometimes already contains
    # mojibake, independent of the HTTP charset. Apply to both public fields.
    if result.get("status") == "ok":
        result["text"] = clean_encoding(result.get("text", ""))
        for match in result.get("match_facts", []):
            for field in ("home_team", "away_team", "competition"):
                if isinstance(match.get(field), str):
                    match[field] = clean_encoding(match[field])
    payload = normalize_output({"club": club, "source_title": title, "source_url": url, "squad": squad,
            "runtime_commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
            "encoding_fix_revision": "unicode-diagnostic-v3",
            "encoding_diagnostic": {"sample_codepoints": [hex(ord(ch)) for ch in result.get("text", "")[max(0, result.get("text", "").find("Atl")):][:18]]},
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "fetch": result, "verified_live": False,
            "note": "Raw page evidence only. Match facts require structured extraction and cross-checking."})
    final_text = payload.get("fetch", {}).get("text", "")
    first_team = (payload.get("fetch", {}).get("match_facts") or [{}])[0].get("home_team", "")
    pos = final_text.find("Atl")
    payload["json_diagnostic"] = {
        "final_text_sample": final_text[pos:pos + 20] if pos >= 0 else "",
        "final_text_codepoints": [hex(ord(ch)) for ch in final_text[pos:pos + 12]] if pos >= 0 else [],
        "first_team": first_team,
        "first_team_codepoints": [hex(ord(ch)) for ch in first_team[:12]],
        "json_roundtrip_equal": json.loads(json.dumps(payload, ensure_ascii=False)) == payload,
    }
    return Response(content=json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii"), media_type="application/json; charset=utf-8")


@router.get("/encoding-check")
def encoding_check():
    """ASCII-only wire diagnostic; no upstream network fetch or personal data."""
    sample = "Atl" + chr(0xE9) + "tico Madrid"
    expected = sample.encode("utf-8")
    payload = {
        "revision": "http-encoding-check-v2",
        "runtime_commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        "expected_name_ascii_escaped": sample.encode("unicode_escape").decode("ascii"),
        "expected_utf8_hex": expected.hex(),
        "expected_codepoints": [hex(ord(char)) for char in sample],
        "expected_content_type": "application/json; charset=utf-8",
        "explanation": "All fields are ASCII so browsers cannot corrupt the diagnostic itself.",
    }
    # Ensure the *actual outgoing body* is ASCII and can be inspected byte-for-byte.
    body = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
    return Response(content=body, media_type="application/json; charset=utf-8",
                    headers={"X-AiFBall-Encoding-Test": "http-encoding-check-v2",
                             "X-AiFBall-Expected-UTF8-Hex": expected.hex()})


@router.get("/encoding-json-check")
def encoding_json_check():
    """Send real non-ASCII Unicode through FastAPI JSONResponse."""
    sample = "Atl" + chr(0xE9) + "tico Madrid"
    payload = {
        "revision": "json-wire-v1",
        "runtime_commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        "name": sample,
        "name_codepoints": [hex(ord(ch)) for ch in sample],
        "expected_utf8_hex": sample.encode("utf-8").hex(),
        "is_real_unicode": chr(0xE9) in sample,
    }
    return Response(content=json.dumps(payload, ensure_ascii=True).encode("ascii"), media_type="application/json; charset=utf-8", headers={"X-AiFBall-Encoding-Test": "json-wire-v2-ascii-safe"})


@router.get("/encoding-wire-inspect")
def encoding_wire_inspect():
    """Inspect the serialized response bytes on the server, using ASCII-only output."""
    sample = "Atl" + chr(0xE9) + "tico Madrid"
    outgoing = JSONResponse(content={"name": sample})
    body = outgoing.body
    raw_utf8 = sample.encode("utf-8")
    mojibake_utf8 = ("Atl" + chr(0xC3) + chr(0xA9) + "tico Madrid").encode("utf-8")
    decoded = json.loads(body.decode("utf-8"))
    return {
        "revision": "wire-inspect-v1",
        "runtime_commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        "response_content_type": outgoing.headers.get("content-type"),
        "response_body_hex": body.hex(),
        "correct_utf8_sequence_present": raw_utf8 in body,
        "mojibake_utf8_sequence_present": mojibake_utf8 in body,
        "decoded_name_codepoints": [hex(ord(ch)) for ch in decoded["name"]],
        "decoded_name_matches_source": decoded["name"] == sample,
        "expected_name_utf8_hex": raw_utf8.hex(),
    }


@router.get("/encoding-html-check")
def encoding_html_check():
    """Visual mobile test with explicit charset."""
    name = "Atl" + chr(0xE9) + "tico Madrid"
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>AiFBall encoding</title></head><body>"
        "<h2>AiFBall encoding check</h2>"
        "<p>Expected: Atl&amp;eacute;tico Madrid</p>"
        "<p>Real Unicode: " + name + "</p>"
        "<p>UTF-8: C3 A9; Unicode: U+00E9</p>"
        "</body></html>"
    )
    return Response(content=html.encode("utf-8"), media_type="text/html; charset=utf-8")

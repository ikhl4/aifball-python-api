"""Conservative discovery of Saudi federation source pages.

Fetches public federation pages only. Text matches are leads, not proof that a
particular squad competes in a given league.
"""
import re
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/research", tags=["verified-research"])
SOURCES = (
    ("SAFF+", "https://saffplus.sa/ar"),
    ("SAFF competitions", "https://www.saff.com.sa/championships.php"),
    ("SAFF regulations and schedules", "https://www.saff.com.sa/files.php"),
)
HEADERS = {"User-Agent": "AiFBallResearch/1.0 (public source discovery)"}

def discover(club: str):
    output = []
    for label, url in SOURCES:
        try:
            response = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
            response.raise_for_status()
            parsed = urlparse(response.url)
            if parsed.scheme != "https" or parsed.hostname not in {"saffplus.sa", "www.saff.com.sa", "saff.com.sa"}:
                raise ValueError("Unexpected redirect destination")
            soup = BeautifulSoup(response.text[:1_000_000], "html.parser")
            for node in soup(["script", "style", "noscript"]):
                node.decompose()
            lines = [re.sub(r"\s+", " ", line).strip() for line in soup.get_text("\n").splitlines()]
            matches = [line[:300] for line in lines if club.casefold() in line.casefold() and len(line) <= 500]
            output.append({"source": label, "url": response.url, "status": "ok",
                           "matching_text": matches[:15], "evidence_level": "discovery_only"})
        except (requests.RequestException, ValueError) as exc:
            output.append({"source": label, "url": url, "status": "unavailable",
                           "error_type": type(exc).__name__, "matching_text": []})
    return output

@router.get("/clubs/discover")
def discover_club(club: str = Query(min_length=2, max_length=100)):
    return {"club": club, "verified_live": False,
            "note": "Matches are discovery leads only. Do not infer squad or competition from these snippets.",
            "sources": discover(club)}

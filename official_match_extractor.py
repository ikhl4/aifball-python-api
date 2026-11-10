"""Conservative structured extraction from official Barcelona first-team result text.

Parsed records are candidates, not independently verified match facts.
"""
import re
from datetime import datetime

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
MONTH = {m: i + 1 for i, m in enumerate(MONTHS)}
DATE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b")
SCORE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–]\s*(\d{1,2})(?!\d)")
COMPETITIONS = (
    ("UEFA Champions League", "UEFA Champions League"),
    ("La Liga", "La Liga"),
    ("Other Club Friendlies", "Club Friendly"),
)
NOISE = ("Chevron", "SVG", "pointing", "right", "label.aria", "caret-down")

def extract_barcelona_results(text, source_url, squad="first_team"):
    if squad != "first_team" or not source_url.startswith("https://www.fcbarcelona.com/en/football/first-team/results"):
        return []
    if not text or "First Team Results" not in text:
        return []
    year_match = re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b", text[:120])
    if not year_match:
        return []
    year = int(year_match.group(1))
    # Use only the first listing; later text on the page can repeat matches in menus.
    listing = text.split("Chevron", 1)[0]
    markers = list(DATE.finditer(listing))
    results = []
    for i, marker in enumerate(markers):
        section = listing[marker.end(): markers[i + 1].start() if i + 1 < len(markers) else len(listing)]
        if len(section) > 350 or any(word in section for word in NOISE):
            continue
        competition = next((name for label, name in COMPETITIONS if label in section), None)
        if not competition:
            continue
        score_matches = list(SCORE.finditer(section))
        if len(score_matches) != 1:
            continue
        score = score_matches[0]
        left, right = section[:score.start()].strip(), section[score.end():].strip()
        # Reject uncertain team boundaries rather than inventing opponent names.
        if not ("FC Barcelona" in left or "FC Barcelona" in right):
            continue
        if not left or not right:
            continue
        if not (left.endswith("FC Barcelona") or right.startswith("FC Barcelona")):
            continue
        try:
            date = datetime(year, MONTH[marker.group(2)], int(marker.group(1))).date().isoformat()
        except ValueError:
            continue
        results.append({"date": date, "competition": competition,
                        "home_context": left, "away_context": right,
                        "home_score": int(score.group(1)), "away_score": int(score.group(2)),
                        "squad": "first_team", "source_url": source_url,
                        "verification": "extracted_unverified"})
    return results

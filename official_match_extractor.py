"""Conservative first-team match candidate extraction from Barcelona's official results page.

A parsed match is source-bound but NOT independently verified.
Unknown team boundaries remain null rather than being guessed.
"""
import re
from datetime import date

SOURCE = "https://www.fcbarcelona.com/en/football/first-team/results"
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
DATE = re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b")
SCORE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–]\s*(\d{1,2})(?!\d)")
MONTH_HEADER = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b")
COMPETITIONS = ("UEFA Champions League", "La Liga")
# Names observed in the official match list. Do not assume arbitrary substrings are team names.
OPPONENTS = (
    "Atlético Madrid", "Aston Villa", "Alavés", "Real Madrid",
    "Paris Saint Germain", "Real Betis", "Galatasaray", "Getafe",
    "Sevilla", "Racing de Santander", "Levante", "Feyenoord",
    "Valencia CF", "Rayo Vallecano", "Athletic Club", "Elche",
)
MOJIBAKE = {"Ã©": "é", "Ã¡": "á", "Ã³": "ó", "Ã­": "í", "Ã±": "ñ", "Ãº": "ú", "Ã¼": "ü"}

def clean_encoding(text):
    # Only repair known mojibake; do not re-encode arbitrary text.
    for bad, good in MOJIBAKE.items():
        text = text.replace(bad, good)
    return text

def _opponent(context, side):
    context = clean_encoding(context).strip()
    candidates = [team for team in OPPONENTS
                  if (context.endswith(team) if side == "home" else context.startswith(team))]
    return max(candidates, key=len) if candidates else None

def extract_barcelona_results(text, source_url, squad="first_team"):
    if squad != "first_team" or source_url != SOURCE or not text or "First Team Results" not in text:
        return []
    listing = clean_encoding(text).split("Chevron", 1)[0]
    markers = list(DATE.finditer(listing))
    results = []
    for i, marker in enumerate(markers):
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(listing)
        section = listing[start:end].strip()
        # Month headings can follow a match and must not be included in away team.
        header = MONTH_HEADER.search(section)
        if header:
            section = section[:header.start()].strip()
        if len(section) > 350:
            continue
        competition = next((name for name in COMPETITIONS if name in section), None)
        if not competition:
            continue
        scores = list(SCORE.finditer(section))
        if len(scores) != 1:
            continue
        score = scores[0]
        left, right = section[:score.start()].strip(), section[score.end():].strip()
        if not left or not right:
            continue
        if left.endswith("FC Barcelona"):
            home, away = "FC Barcelona", _opponent(right, "away")
        elif right.startswith("FC Barcelona"):
            home, away = _opponent(left, "home"), "FC Barcelona"
        else:
            continue
        if not home or not away:
            continue
        # Determine year from the closest preceding month heading, not a fixed global year.
        prefix = listing[:marker.start()]
        headers = list(MONTH_HEADER.finditer(prefix))
        if not headers:
            continue
        year = int(headers[-1].group(1))
        try:
            match_date = date(year, MONTHS[marker.group(2)], int(marker.group(1))).isoformat()
        except ValueError:
            continue
        results.append({
            "date": match_date, "competition": competition,
            "home_team": home, "away_team": away,
            "home_score": int(score.group(1)), "away_score": int(score.group(2)),
            "squad": "first_team", "source_url": source_url,
            "verification": "extracted_unverified",
        })
    return results

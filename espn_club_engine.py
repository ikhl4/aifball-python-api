"""Stable ESPN-only cross-competition club results; no experimental verification providers."""
from datetime import datetime, timezone
from fastapi import APIRouter, Query
import requests
import re
import os
import unicodedata

router = APIRouter(prefix="/research/live", tags=["club-latest-match"])
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"

def normalized_team(name):
    name = re.sub(r"\s+", " ", str(name or "").casefold().strip())
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))

MAJOR_COMPETITIONS = {
    "ksa.1": "Saudi Pro League", "ksa.kings.cup": "King's Cup",
    "afc.champions": "AFC Champions League Elite", "afc.cup": "AFC Champions League Two",
    "eng.1": "Premier League", "eng.fa": "FA Cup", "eng.league_cup": "EFL Cup",
    "esp.1": "La Liga", "esp.copa_del_rey": "Copa del Rey", "esp.super_cup": "Spanish Super Cup",
    "ita.1": "Serie A", "ita.coppa_italia": "Coppa Italia",
    "ger.1": "Bundesliga", "ger.dfb_pokal": "DFB-Pokal",
    "fra.1": "Ligue 1", "fra.coupe_de_france": "Coupe de France",
    "uefa.champions": "UEFA Champions League", "uefa.europa": "UEFA Europa League",
    "uefa.europa.conf": "UEFA Conference League", "uefa.super_cup": "UEFA Super Cup",
    "fifa.cwc": "FIFA Club World Cup", "fifa.world": "FIFA World Cup",
    "conmebol.libertadores": "Copa Libertadores",
    "conmebol.sudamericana": "Copa Sudamericana",
    "caf.champions": "CAF Champions League",
    "concacaf.champions": "CONCACAF Champions Cup",
    "usa.1": "MLS", "usa.open": "US Open Cup",
    "club.friendly": "Club Friendlies",
}
# Scope requests to the competitions a club can actually play.
CLUB_COMPETITIONS = {
    "al hilal": ("ksa.1", "ksa.kings.cup", "afc.champions", "fifa.cwc"),
    "al ittihad": ("ksa.1", "ksa.kings.cup", "afc.champions", "fifa.cwc"),
    "al nassr": ("ksa.1", "ksa.kings.cup", "afc.champions", "afc.cup"),
    "al ahli": ("ksa.1", "ksa.kings.cup", "afc.champions", "afc.cup"),
    "real madrid": ("esp.1", "esp.copa_del_rey", "esp.super_cup", "uefa.champions", "fifa.cwc"),
    "barcelona": ("esp.1", "esp.copa_del_rey", "esp.super_cup", "uefa.champions", "fifa.cwc"),
    "manchester city": ("eng.1", "eng.fa", "eng.league_cup", "uefa.champions", "fifa.cwc"),
    "paris saint germain": ("fra.1", "fra.coupe_de_france", "uefa.champions", "fifa.cwc"),
}
CLUB_NAME_KEYS = {
    "الهلال": "al hilal", "al-hilal": "al hilal",
    "الاتحاد": "al ittihad", "al-ittihad": "al ittihad",
    "النصر": "al nassr", "al-nassr": "al nassr",
    "الأهلي": "al ahli", "al-ahli": "al ahli",
    "ريال مدريد": "real madrid", "برشلونة": "barcelona", "fc barcelona": "barcelona",
    "مانشستر سيتي": "manchester city", "man city": "manchester city",
    "باريس سان جيرمان": "paris saint germain", "psg": "paris saint germain",
}
CLUB_MATCH_ALIASES = {
    "al hilal": ("al hilal", "al-hilal", "al hilal saudi fc"),
    "al ittihad": ("al ittihad", "al-ittihad", "al ittihad club"),
    "al nassr": ("al nassr", "al-nassr", "al nassr fc"),
    "al ahli": ("al ahli", "al-ahli", "al ahli saudi"),
    "real madrid": ("real madrid", "real madrid cf"),
    "barcelona": ("barcelona", "fc barcelona"),
    "manchester city": ("manchester city", "man city"),
    "paris saint germain": ("paris saint germain", "paris saint-germain", "psg"),
}

def _fetch_competition_day(league, day):
    try:
        response = requests.get(
            ESPN_URL.format(league=league),
            params={"dates": day.strftime("%Y%m%d"), "limit": 200},
            timeout=(3, 7), allow_redirects=False,
            headers={"User-Agent": "AiFBallResearch/1.0", "Accept": "application/json"},
        )
        if response.status_code != 200:
            return league, "http_" + str(response.status_code), []
        if len(response.content) > 500_000:
            return league, "response_too_large", []
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("events", []), list):
            return league, "invalid_payload", []
        return league, "ok", payload.get("events", [])
    except requests.Timeout:
        return league, "timeout", []
    except requests.RequestException:
        return league, "connection_failed", []
    except ValueError:
        return league, "invalid_json", []


@router.get("/club-latest-match")
def club_latest_match(
    club: str = Query(min_length=2, max_length=100),
    days: int = Query(14, ge=1, le=31),
):
    """Latest completed match across configured competitions; ESPN-only evidence."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import timedelta
    key = CLUB_NAME_KEYS.get(club.strip().casefold(), club.strip().casefold())
    leagues = CLUB_COMPETITIONS.get(key)
    if not leagues:
        return {"club": club, "status": "not_configured", "verified_independent": False,
                "note": "Club not configured for cross-competition lookup."}
    target = {normalized_team(n) for n in CLUB_MATCH_ALIASES[key]}
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days)
    jobs = [(league, start + timedelta(days=i))
            for league in leagues for i in range(days + 1)]
    diagnostics = {league: {} for league in leagues}
    matches, seen = [], set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_fetch_competition_day, league, day) for league, day in jobs]
        for future in as_completed(futures):
            league, result, events = future.result()
            diagnostics[league][result] = diagnostics[league].get(result, 0) + 1
            for event in events:
                if not isinstance(event, dict):
                    continue
                competitions = event.get("competitions") or []
                if not competitions or not isinstance(competitions[0], dict):
                    continue
                competition = competitions[0]
                teams = {c.get("homeAway"): c for c in competition.get("competitors", [])
                         if isinstance(c, dict)}
                home, away = teams.get("home"), teams.get("away")
                if not home or not away:
                    continue
                def names(entry):
                    team = entry.get("team") or {}
                    return {normalized_team(team.get(k)) for k in
                            ("displayName", "name", "shortDisplayName")}
                if not (target & (names(home) | names(away))):
                    continue
                status = competition.get("status") or event.get("status") or {}
                if not (status.get("type") or {}).get("completed", False):
                    continue
                if home.get("score") is None or away.get("score") is None:
                    continue
                event_id = str(event.get("id") or "")
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                matches.append({
                    "event_id": event_id, "date_utc": event.get("date"),
                    "competition": MAJOR_COMPETITIONS[league], "competition_code": league,
                    "home_team": (home.get("team") or {}).get("displayName"),
                    "away_team": (away.get("team") or {}).get("displayName"),
                    "home_score": home.get("score"), "away_score": away.get("score"),
                    "completed": True, "source": "ESPN scoreboard",
                    "verification": "espn_only_unverified",
                })
    matches.sort(key=lambda m: m.get("date_utc") or "", reverse=True)
    verification_summary = {"status": "not_performed", "checked": 0, "verified": 0, "method": "espn_only"}
    latest = matches[0] if matches else None
    full_coverage = all(diagnostics[league].get("ok", 0) == days + 1 for league in leagues)
    return {
        "club": club, "status": "found" if latest else
            ("no_match_in_covered_window" if full_coverage else "incomplete_coverage"),
        "latest_match": latest, "matches_found": len(matches),
        "matches": matches[:20], "competitions_checked": list(leagues),
        "window_utc": {"start": start.isoformat(), "end": today.isoformat()},
        "request_diagnostics": diagnostics, "coverage_complete": full_coverage,
        "verified_independent": bool(latest and latest.get("verification") == "verified_independent"),
        "verification_summary": verification_summary,
        "source": "ESPN scoreboard",
        "runtime_commit": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
        "note": "ESPN-only match discovery. Independent verification is not performed.",
    }



"""Global football source routing: source discovery, not unverified claims.

The registry is intentionally curated and deterministic. Provider APIs are not
called here; source availability and coverage must be checked separately.
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/research", tags=["global-source-routing"])

REGISTRY = {
    "BR": {"federation": [("CBF", "https://www.cbf.com.br/")],
           "league": [("CBF competitions", "https://www.cbf.com.br/futebol-brasileiro/competicoes")]},
    "AR": {"federation": [("AFA", "https://www.afa.com.ar/")],
           "league": [("Liga Profesional", "https://www.ligaprofesional.ar/")]},
    "JP": {"federation": [("JFA", "https://www.jfa.jp/eng/match/")],
           "league": [("J.League", "https://www.jleague.jp/en/")]},
    "ZA": {"federation": [("SAFA", "https://www.safa.net/")],
           "league": [("Premier Soccer League", "https://www.psl.co.za/")]},
    "SA": {"federation": [("SAFF", "https://www.saff.com.sa/"), ("SAFF+", "https://saffplus.sa/ar")],
           "league": [("Saudi Pro League", "https://www.spl.com.sa/")]},
    "GB": {"federation": [("The FA", "https://www.thefa.com/")],
           "league": [("Premier League", "https://www.premierleague.com/")]},
    "ES": {"federation": [("RFEF", "https://rfef.es/")],
           "league": [("LaLiga", "https://www.laliga.com/")]},
    "IT": {"federation": [("FIGC", "https://www.figc.it/")],
           "league": [("Lega Serie A", "https://www.legaseriea.it/")]},
    "DE": {"federation": [("DFB", "https://www.dfb.de/")],
           "league": [("Bundesliga", "https://www.bundesliga.com/")]},
    "FR": {"federation": [("FFF", "https://www.fff.fr/")],
           "league": [("LFP", "https://www.lfp.fr/")]},
    "US": {"federation": [("US Soccer", "https://www.ussoccer.com/")],
           "league": [("MLS", "https://www.mlssoccer.com/")]},
    "AE": {"federation": [("UAE FA", "https://www.uaefa.ae/")],
           "league": [("UAE Pro League", "https://www.uaeproleague.ae/ar")]},
    "QA": {"federation": [("QFA", "https://www.qfa.qa/")],
           "league": [("QSL", "https://www.qsl.qa/")]},
    "EG": {"federation": [("EFA", "https://www.efa.eg/")],
           "league": [("Egyptian Pro League", "https://www.egyptianproleague.com/league")]},
}
GLOBAL = [("FIFA", "https://www.fifa.com/")]
CONFEDERATIONS = {
    "UEFA": ("UEFA", "https://www.uefa.com/"),
    "AFC": ("AFC", "https://www.the-afc.com/"),
    "CONMEBOL": ("CONMEBOL", "https://www.conmebol.com/"),
    "CAF": ("CAF", "https://www.cafonline.com/"),
    "CONCACAF": ("CONCACAF", "https://www.concacaf.com/"),
}
COUNTRY_CONFEDERATION = {
    **dict.fromkeys(("SA", "AE", "QA", "JP"), "AFC"),
    **dict.fromkeys(("GB", "ES", "IT", "DE", "FR"), "UEFA"),
    **dict.fromkeys(("BR", "AR"), "CONMEBOL"),
    **dict.fromkeys(("EG", "ZA"), "CAF"),
    "US": "CONCACAF",
}
STATS = ["FotMob", "365Scores", "SofaScore"]
# Do not treat country of an international competition as club nationality.
ALIASES = {
    "البرازيل": "BR", "brazil": "BR", "brasil": "BR",
    "الأرجنتين": "AR", "argentina": "AR",
    "اليابان": "JP", "japan": "JP",
    "جنوب أفريقيا": "ZA", "جنوب افريقيا": "ZA", "south africa": "ZA",
    "السعودية": "SA", "saudi arabia": "SA", "ksa": "SA",
    "إنجلترا": "GB", "england": "GB", "uk": "GB",
    "إسبانيا": "ES", "spain": "ES",
    "إيطاليا": "IT", "italy": "IT",
    "ألمانيا": "DE", "germany": "DE",
    "فرنسا": "FR", "france": "FR",
    "أمريكا": "US", "usa": "US", "united states": "US",
    "الإمارات": "AE", "uae": "AE",
    "قطر": "QA", "qatar": "QA",
    "مصر": "EG", "egypt": "EG",
}

class RouteRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    competition: str | None = Field(default=None, max_length=200)
    season: str | None = Field(default=None, max_length=30)
    squad: str = Field(default="first_team", pattern="^(first_team|u21|u19|u17|futsal|unknown)$")

def plan(request: RouteRequest):
    raw = (request.country or "").strip()
    country = ALIASES.get(raw.casefold(), raw.upper())
    country = country if country in REGISTRY else None
    sources = []
    if country:
        for kind, entries in REGISTRY[country].items():
            sources.extend({"name": name, "url": url, "kind": kind, "country": country}
                           for name, url in entries)
    federation = COUNTRY_CONFEDERATION.get(country)
    international = GLOBAL + ([CONFEDERATIONS[federation]] if federation else [])
    sources.extend({"name": name, "url": url, "kind": "international", "country": None}
                   for name, url in international)
    return {
        "query": request.query, "country": country, "country_resolved": country is not None,
        "competition": request.competition, "season": request.season, "squad": request.squad,
        "official_sources": sources,
        "statistics_providers": [{"name": name, "status": "not_queried"} for name in STATS],
        "live_verified": False,
        "note": "Source plan only. No match, player or club facts have been fetched.",
    }

@router.post("/sources/plan")
def plan_sources(request: RouteRequest):
    return plan(request)

@router.get("/sources/countries")
def supported_countries():
    return {"countries": sorted(REGISTRY), "fallback": [x[0] for x in GLOBAL]}


import os
import re
import math
import logging
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional
from urllib.parse import urlencode

import requests
import pandas as pd
import numpy as np
import LanusStats as ls

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware


# ==========================================
# AiFBall Python API
# ==========================================

app = FastAPI(
    title="AiFBall Football Data API",
    version="2.0.0"
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aifball")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS",
        "https://aifball.com,https://www.aifball.com"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

FOTMOB_BASE = "https://www.fotmob.com/api/data"

# لا تفعل الوصول الآلي إلى FotMob
# إلا بعد التأكد من وجود التصريح المناسب.
FOTMOB_ENABLED = (
    os.getenv("FOTMOB_ENABLED", "false").lower()
    == "true"
)

HTTP_TIMEOUT = 15

session = requests.Session()
session.headers.update({
    "Accept": "application/json",
    "User-Agent": "AiFBall/2.0"
})


# ==========================================
# Helpers
# ==========================================

def sanitize(value):
    if value is None:
        return None

    if isinstance(value, np.generic):
        return sanitize(value.item())

    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, dict):
        return {
            str(k): sanitize(v)
            for k, v in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]

    if pd.isna(value) is True:
        return None

    return value


def df_to_json(df):
    if df is None:
        return []

    if not isinstance(df, pd.DataFrame):
        if isinstance(df, list):
            return sanitize(df)

        raise HTTPException(
            status_code=502,
            detail="صيغة بيانات المصدر غير مدعومة"
        )

    if df.empty:
        return []

    clean = df.replace(
        [np.inf, -np.inf],
        np.nan
    )

    return sanitize(
        clean.to_dict(orient="records")
    )


def source_error(source, error):
    logger.exception(
        "Source %s failed: %s",
        source,
        error
    )

    raise HTTPException(
        status_code=502,
        detail=f"تعذر جلب البيانات من {source}"
    )


def require_fotmob():
    if not FOTMOB_ENABLED:
        raise HTTPException(
            status_code=503,
            detail=(
                "مصدر FotMob غير مفعل. "
                "يلزم التصريح المناسب ثم ضبط "
                "FOTMOB_ENABLED=true"
            )
        )


def fotmob_request(path, params=None):
    require_fotmob()

    url = f"{FOTMOB_BASE}/{path}"

    try:
        response = session.get(
            url,
            params=params or {},
            timeout=HTTP_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, (dict, list)):
            raise ValueError(
                "Unexpected JSON structure"
            )

        return data

    except requests.Timeout:
        raise HTTPException(
            status_code=504,
            detail="انتهت مهلة الاتصال بمصدر FotMob"
        )

    except requests.RequestException as error:
        logger.warning(
            "FotMob request failed: %s",
            error
        )

        raise HTTPException(
            status_code=502,
            detail="تعذر الاتصال بمصدر FotMob"
        )

    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="استجابة FotMob غير صالحة"
        )


def as_number(value):
    if value is None or isinstance(value, bool):
        return None

    try:
        result = float(value)

        if not math.isfinite(result):
            return None

        return int(result) if result.is_integer() else result

    except (ValueError, TypeError):
        return None


def first_number(item, *keys):
    for key in keys:
        value = as_number(item.get(key))

        if value is not None:
            return value

    return None


def normalize_text(value):
    text = unicodedata.normalize(
        "NFKD",
        str(value or "")
    )

    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = re.sub(
        r"[\u064b-\u065f]",
        "",
        text
    )

    text = (
        text.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
    )

    return " ".join(text.casefold().split())


# ==========================================
# League aliases
# These are search aliases, not guaranteed IDs.
# ==========================================

LEAGUE_ALIASES = {
    "ksa.1": [
        "دوري روشن",
        "الدوري السعودي",
        "saudi pro league"
    ],
    "egy.1": [
        "الدوري المصري",
        "الدوري المصري الممتاز",
        "egyptian premier league"
    ],
    "uae.1": [
        "الدوري الاماراتي",
        "دوري ادنوك",
        "uae pro league"
    ],
    "qat.1": [
        "الدوري القطري",
        "دوري نجوم قطر",
        "qatar stars league"
    ],
    "kuw.1": [
        "الدوري الكويتي",
        "دوري زين الكويتي",
        "kuwait premier league"
    ],
    "bhr.1": [
        "الدوري البحريني",
        "bahraini premier league"
    ],
    "oma.1": [
        "الدوري العماني",
        "oman professional league"
    ],
    "irq.1": [
        "الدوري العراقي",
        "iraq stars league"
    ],
    "eng.1": [
        "الدوري الانجليزي",
        "premier league"
    ],
    "esp.1": [
        "الدوري الاسباني",
        "la liga"
    ],
    "ita.1": [
        "الدوري الايطالي",
        "serie a"
    ],
    "ger.1": [
        "الدوري الالماني",
        "bundesliga"
    ],
    "fra.1": [
        "الدوري الفرنسي",
        "ligue 1"
    ],
}

# معرفات موثقة في المشروع أو المصادر.
# لا نضيف معرفًا غير متحقق منه.
KNOWN_FOTMOB_IDS = {
    "ksa.1": 536,
    "eng.1": 47,
    "esp.1": 87,
    "ita.1": 55,
    "ger.1": 54,
    "fra.1": 53,
    "uefa.champions": 42,
}


def resolve_league_id(league):
    value = str(league).strip()

    if value.isdigit():
        result = int(value)

        if result > 0:
            return result

    if value in KNOWN_FOTMOB_IDS:
        return KNOWN_FOTMOB_IDS[value]

    raise HTTPException(
        status_code=404,
        detail=(
            "معرف البطولة غير معروف. "
            "استخدم /leagues/search لاكتشاف "
            "معرف FotMob الصحيح."
        )
    )


def normalize_season(season):
    if not season:
        return None

    value = season.strip()

    if re.fullmatch(r"\d{4}/\d{4}", value):
        return value

    if re.fullmatch(r"\d{4}-\d{4}", value):
        return value.replace("-", "/")

    if re.fullmatch(r"\d{4}", value):
        return value

    raise HTTPException(
        status_code=400,
        detail="صيغة الموسم غير صحيحة"
    )


# ==========================================
# League directory
# ==========================================

@lru_cache(maxsize=1)
def get_league_directory():
    payload = fotmob_request("allLeagues")

    if not isinstance(payload, dict):
        return []

    result = []
    seen = set()

    def add_league(item, country=None):
        if not isinstance(item, dict):
            return

        league_id = as_number(item.get("id"))

        name = item.get("name")

        if league_id is None or not name:
            return

        league_id = int(league_id)

        if league_id in seen:
            return

        seen.add(league_id)

        result.append({
            "id": league_id,
            "name": str(name),
            "localizedName": item.get(
                "localizedName"
            ),
            "country": country,
            "pageUrl": item.get("pageUrl"),
        })

    for item in payload.get("popular", []):
        add_league(item)

    for item in payload.get("international", []):
        add_league(item, "International")

    for country in payload.get("countries", []):
        if not isinstance(country, dict):
            continue

        country_name = (
            country.get("name") or
            country.get("ccode")
        )

        for item in country.get("leagues", []):
            add_league(item, country_name)

    return result


@app.get("/leagues/search")
def search_leagues(
    q: str = Query(..., min_length=2, max_length=100),
    limit: int = Query(20, ge=1, le=100)
):
    require_fotmob()

    query = normalize_text(q)

    aliases = []

    for code, names in LEAGUE_ALIASES.items():
        if query == normalize_text(code):
            aliases.extend(names)

        for name in names:
            normalized = normalize_text(name)

            if query == normalized:
                aliases.extend(names)
                aliases.append(code)
                break

    terms = [query] + [
        normalize_text(value)
        for value in aliases
    ]

    directory = get_league_directory()

    matches = []

    for league in directory:
        searchable = normalize_text(
            " ".join([
                str(league.get("name") or ""),
                str(league.get("localizedName") or ""),
                str(league.get("country") or "")
            ])
        )

        if any(
            term and term in searchable
            for term in terms
        ):
            matches.append(league)

    return {
        "source": "FotMob",
        "query": q,
        "count": len(matches),
        "results": matches[:limit]
    }


@app.get("/leagues")
def list_leagues(
    limit: int = Query(100, ge=1, le=500)
):
    require_fotmob()

    leagues = get_league_directory()

    return {
        "source": "FotMob",
        "count": len(leagues),
        "results": leagues[:limit]
    }


# ==========================================
# FotMob standings
# ==========================================

def normalize_standing_row(raw):
    if not isinstance(raw, dict):
        return None

    name = raw.get("name")

    if not name:
        return None

    gf = None
    ga = None

    scores = raw.get("scoresStr")

    if isinstance(scores, str):
        match = re.fullmatch(
            r"\s*(\d+)\s*-\s*(\d+)\s*",
            scores
        )

        if match:
            gf = int(match.group(1))
            ga = int(match.group(2))

    gf = first_number(
        raw,
        "goalsFor",
        "gf"
    ) if gf is None else gf

    ga = first_number(
        raw,
        "goalsAgainst",
        "ga"
    ) if ga is None else ga

    gd = first_number(
        raw,
        "goalConDiff",
        "goalDifference",
        "gd"
    )

    if gd is None and gf is not None and ga is not None:
        gd = gf - ga

    team_id = raw.get("id")

    logo = None

    if team_id is not None:
        if str(team_id).isdigit():
            logo = (
                "https://images.fotmob.com/"
                "image_resources/logo/teamlogo/"
                f"{team_id}.png"
            )

    return {
        "id": str(team_id or name),
        "pos": first_number(
            raw,
            "idx",
            "rank",
            "position"
        ),
        "name": str(name),
        "logo": logo,
        "played": first_number(raw, "played"),
        "won": first_number(raw, "wins"),
        "draw": first_number(raw, "draws"),
        "lost": first_number(raw, "losses"),
        "gf": gf,
        "ga": ga,
        "gd": gd,
        "pts": first_number(raw, "pts", "points")
    }


def extract_fotmob_groups(payload):
    raw_tables = payload.get("table")

    if not isinstance(raw_tables, list):
        return []

    groups = []

    for index, table_item in enumerate(raw_tables):
        if not isinstance(table_item, dict):
            continue

        data = table_item.get("data", {})

        if not isinstance(data, dict):
            continue

        table = data.get("table")

        candidate_groups = []

        if isinstance(table, dict):
            rows = table.get("all")

            if isinstance(rows, list):
                candidate_groups.append({
                    "name": (
                        data.get("leagueName")
                        or "الترتيب العام"
                    ),
                    "rows": rows
                })

        # بعض البطولات تعيد tables
        # بدل table، ومنها مجموعات متعددة.
        split_tables = data.get("tables")

        if isinstance(split_tables, list):
            for group_index, item in enumerate(split_tables):
                if not isinstance(item, dict):
                    continue

                nested = item.get("table", {})

                if isinstance(nested, dict):
                    rows = nested.get("all")
                else:
                    rows = None

                if not isinstance(rows, list):
                    continue

                candidate_groups.append({
                    "name": (
                        item.get("name")
                        or item.get("leagueName")
                        or f"المجموعة {group_index + 1}"
                    ),
                    "rows": rows
                })

        for candidate in candidate_groups:
            rows = [
                normalized
                for raw in candidate["rows"]
                if (
                    normalized := normalize_standing_row(raw)
                ) is not None
            ]

            if not rows:
                continue

            groups.append({
                "id": f"group-{index + 1}-{len(groups) + 1}",
                "name": candidate["name"],
                "rows": rows
            })

    return groups


@app.get("/fotmob/standings")
def get_fotmob_standings(
    league: str = Query("ksa.1", max_length=100),
    season: Optional[str] = None
):
    league_id = resolve_league_id(league)

    params = {"id": league_id}

    requested_season = normalize_season(season)

    if requested_season:
        params["season"] = requested_season

    payload = fotmob_request(
        "leagues",
        params
    )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail="استجابة البطولة غير صالحة"
        )

    details = payload.get("details", {})

    if not isinstance(details, dict):
        details = {}

    returned_season = details.get("selectedSeason")

    # لا نعرض موسمًا مختلفًا عن المطلوب.
    if requested_season and returned_season:
        if requested_season != str(returned_season):
            raise HTTPException(
                status_code=404,
                detail=(
                    "المصدر أعاد موسمًا مختلفًا "
                    "عن الموسم المطلوب"
                )
            )

    groups = extract_fotmob_groups(payload)

    if not groups:
        raise HTTPException(
            status_code=404,
            detail=(
                "لا توجد بيانات ترتيب مؤكدة "
                "لهذه البطولة في FotMob"
            )
        )

    return {
        "source": "FotMob",
        "league": str(league),
        "leagueId": league_id,
        "leagueName": details.get("name"),
        "season": returned_season,
        "seasonName": returned_season,
        "groups": groups,
        "rows": groups[0]["rows"],
        "groupCount": len(groups),
        "updatedAt": datetime.now(
            timezone.utc
        ).isoformat()
    }


# ==========================================
# Health
# ==========================================

@app.get("/")
def read_root():
    return {
        "status": "AiFBall Python API is running",
        "version": "2.0.0",
        "fotmobEnabled": FOTMOB_ENABLED
    }


# ==========================================
# 365Scores
# ==========================================

@app.get("/365scores/shotmap")
def get_365_shotmap(match_url: str):
    try:
        scores = ls.ThreeSixFiveScores()
        df = scores.get_match_shotmap(
            match_url=match_url
        )

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("365Scores", error)


@app.get("/365scores/heatmap")
def get_365_heatmap(
    match_url: str,
    player_name: str
):
    try:
        scores = ls.ThreeSixFiveScores()

        heatmap_url = scores.get_player_heatmap_match(
            player=player_name,
            match_url=match_url
        )

        return {"url": heatmap_url}

    except HTTPException:
        raise
    except Exception as error:
        source_error("365Scores", error)


@app.get("/365scores/lineup")
def get_365_lineup(match_url: str):
    try:
        scores = ls.ThreeSixFiveScores()

        df = scores.get_players_info(
            match_url=match_url
        )

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("365Scores", error)


# ==========================================
# SofaScore
# ==========================================

@app.get("/sofascore/shotmap")
def get_sofa_shotmap(match_url: str):
    try:
        sofa = ls.SofaScore()

        df = sofa.get_match_shotmap(
            match_url=match_url
        )

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("SofaScore", error)


@app.get("/sofascore/heatmap")
def get_sofa_heatmap(
    match_url: str,
    player_name: str
):
    try:
        sofa = ls.SofaScore()

        heatmap_url = sofa.get_player_heatmap_match(
            player=player_name,
            match_url=match_url
        )

        return {"url": heatmap_url}

    except HTTPException:
        raise
    except Exception as error:
        source_error("SofaScore", error)


# ==========================================
# FotMob advanced statistics
# ==========================================

@app.get("/fotmob/table")
def get_fotmob_table(
    league: str = "ksa.1",
    season: str = "2026",
    stat: str = "xg"
):
    require_fotmob()

    league_id = resolve_league_id(league)

    allowed_stats = {
        "all",
        "home",
        "away",
        "form",
        "xg"
    }

    if stat not in allowed_stats:
        raise HTTPException(
            status_code=400,
            detail="نوع الجدول غير مدعوم"
        )

    # جداول FotMob العادية تمر عبر
    # /fotmob/standings، وليس إحصائيات xG.
    if stat == "all":
        return get_fotmob_standings(
            league=league,
            season=season
        )

    try:
        fotmob = ls.FotMob()

        # ملاحظة: توقيع get_season_tables
        # يختلف بين إصدارات LanusStats.
        # نتحقق من التوافق بدل اختلاق نتيجة.
        import inspect

        signature = inspect.signature(
            fotmob.get_season_tables
        )

        if "league_id" in signature.parameters:
            df = fotmob.get_season_tables(
                league_id=league_id,
                season=season,
                stat=stat
            )
        else:
            raise HTTPException(
                status_code=501,
                detail=(
                    "إصدار LanusStats الحالي يحتاج "
                    "إلى محول متوافق لجداول "
                    "FotMob المتقدمة"
                )
            )

        rows = df_to_json(df)

        if not rows:
            raise HTTPException(
                status_code=404,
                detail="لا توجد بيانات مؤكدة"
            )

        return {
            "source": "FotMob",
            "league": league,
            "season": season,
            "stat": stat,
            "data": rows
        }

    except HTTPException:
        raise
    except Exception as error:
        source_error("FotMob", error)


@app.get("/fotmob/match")
def get_fotmob_match(match_url: str):
    require_fotmob()

    try:
        fotmob = ls.FotMob()

        df = fotmob.get_match_data(
            match_url=match_url
        )

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("FotMob", error)


# ==========================================
# FBref
# ==========================================

@app.get("/fbref/team-stats")
def get_fbref_team_stats(
    stat_type: str,
    league: str,
    season: str
):
    try:
        fbref = ls.Fbref()

        df = fbref.get_teams_season_stats(
            stat_type,
            league,
            season=season
        )

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("FBref", error)


@app.get("/fbref/player-stats")
def get_fbref_player_stats(
    stat_type: str,
    league: str,
    season: str,
    player_name: Optional[str] = None
):
    try:
        fbref = ls.Fbref()

        df = fbref.get_player_season_stats(
            stat_type,
            league,
            season=season
        )

        if (
            player_name
            and df is not None
            and not df.empty
        ):
            mask = df.apply(
                lambda row: row.astype(str)
                .str.contains(
                    player_name,
                    case=False,
                    regex=False
                )
                .any(),
                axis=1
            )

            df = df[mask]

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("FBref", error)


# ==========================================
# Transfermarkt
# ==========================================

@app.get("/transfermarkt/player-value")
def get_tm_player_value(player_name: str):
    try:
        tm = ls.Transfermarkt()

        df = tm.get_player_market_value(
            player_name
        )

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("Transfermarkt", error)


@app.get("/transfermarkt/team-transfers")
def get_tm_team_transfers(
    team_name: str,
    season: str
):
    try:
        tm = ls.Transfermarkt()

        df = tm.get_team_transfers(
            team_name,
            season
        )

        return {"data": df_to_json(df)}

    except HTTPException:
        raise
    except Exception as error:
        source_error("Transfermarkt", error)

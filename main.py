from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import LanusStats as ls
import pandas as pd
import numpy as np
import math

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # للسماح لموقعك بالاتصال
    allow_methods=["*"],
    allow_headers=["*"],
)

# دالة تنظيف البيانات قبل إرسالها كـ JSON
def df_to_json(df):
    if df is None or df.empty:
        return []
    
    # استبدال القيم اللانهائية (Inf) بـ NaN
    df = df.replace([np.inf, -np.inf], np.nan)
    
    # تحويل الـ DataFrame إلى قائمة من القواميس
    records = df.to_dict(orient="records")
    
    # دالة مساعدة لتحويل أي قيمة عائمة غير صالحة (NaN) إلى None
    def sanitize(obj):
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        return obj
    
    # تنظيف كل سجل قبل إرجاعه
    return [{k: sanitize(v) for k, v in record.items()} for record in records]

@app.get("/")
def read_root():
    return {"status": "AiFBall Python API is running!"}

# ==========================================
# 1. مصادر 365Scores و SofaScore
# ==========================================
@app.get("/365scores/shotmap")
def get_365_shotmap(match_url: str):
    try:
        scores = ls.ThreeSixFiveScores()
        df = scores.get_match_shotmap(match_url=match_url)
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/365scores/heatmap")
def get_365_heatmap(match_url: str, player_name: str):
    try:
        scores = ls.ThreeSixFiveScores()
        heatmap_url = scores.get_player_heatmap_match(player=player_name, match_url=match_url)
        return {"url": heatmap_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/365scores/lineup")
def get_365_lineup(match_url: str):
    try:
        scores = ls.ThreeSixFiveScores()
        df = scores.get_players_info(match_url=match_url)
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
@app.get("/sofascore/shotmap")
def get_sofa_shotmap(match_url: str):
    try:
        sofa = ls.SofaScore()
        df = sofa.get_match_shotmap(match_url=match_url)
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/sofascore/heatmap")
def get_sofa_heatmap(match_url: str, player_name: str):
    try:
        sofa = ls.SofaScore()
        heatmap_url = sofa.get_player_heatmap_match(player=player_name, match_url=match_url)
        return {"url": heatmap_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 2. FotMob (جداول، خرائط تسديد، إحصائيات)
# ==========================================
@app.get("/fotmob/table")
def get_fotmob_table(league: str = "ksa.1", season: str = "2026", stat: str = "xg"):
    try:
        fotmob = ls.FotMob()
        
        # 🌟 خريطة تحويل أكواد الدوريات إلى أرقام FotMob الحقيقية
        league_ids = {
            "ksa.1": 536,         # دوري روشن السعودي
            "eng.1": 47,          # الدوري الإنجليزي
            "esp.1": 87,          # الدوري الإسباني
            "ita.1": 55,          # الدوري الإيطالي
            "ger.1": 54,          # الدوري الألماني
            "fra.1": 53,          # الدوري الفرنسي
            "uefa.champions": 42  # دوري أبطال أوروبا
        }
        
        # إذا لم يجد الكود، الافتراضي هو الدوري السعودي
        league_id = league_ids.get(league, 536)
        
        # جلب البيانات باستخدام الرقم الصحيح
        df = fotmob.get_season_tables(league_id=league_id, season=season, stat=stat)
        
        if df is None or df.empty:
            return {"error": "لم يتم العثور على بيانات لهذا الدوري."}
            
        return {"data": df_to_json(df)}
    except Exception as e:
        print(f"Error fetching table: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fotmob/match")
def get_fotmob_match(match_url: str):
    try:
        fotmob = ls.FotMob()
        df = fotmob.get_match_data(match_url=match_url)
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 3. FBRef (إحصائيات فرق ولاعبين)
# ==========================================
@app.get("/fbref/team-stats")
def get_fbref_team_stats(stat_type: str, league: str, season: str):
    try:
        fbref = ls.Fbref()
        df = fbref.get_teams_season_stats(stat_type, league, season=season)
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/fbref/player-stats")
def get_fbref_player_stats(stat_type: str, league: str, season: str, player_name: str = None):
    try:
        fbref = ls.Fbref()
        df = fbref.get_player_season_stats(stat_type, league, season=season)
        
        # إذا تم تمرير اسم لاعب، نقوم بفلترة النتيجة
        if player_name and df is not None and not df.empty:
            # البحث عن اللاعب (بشكل تقريبي لتفادي مشاكل الهمزات والمسافات)
            mask = df.apply(lambda row: row.astype(str).str.contains(player_name, case=False).any(), axis=1)
            df = df[mask]
            
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 4. Transfermarkt (قيم سوقية وانتقالات)
# ==========================================
@app.get("/transfermarkt/player-value")
def get_tm_player_value(player_name: str):
    try:
        tm = ls.Transfermarkt()
        df = tm.get_player_market_value(player_name)
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/transfermarkt/team-transfers")
def get_tm_team_transfers(team_name: str, season: str):
    try:
        tm = ls.Transfermarkt()
        df = tm.get_team_transfers(team_name, season)
        return {"data": df_to_json(df)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

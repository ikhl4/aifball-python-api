from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import LanusStats as ls

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # للسماح لموقعك بالاتصال
    allow_methods=["*"],
    allow_headers=["*"],
)

def df_to_json(df):
    if df is None or df.empty:
        return []
    return df.to_dict(orient="records")

@app.get("/")
def read_root():
    return {"status": "AiFBall Python API is running!"}

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

"""Evidence-gated club research: preserves squad and competition identity.

This endpoint validates supplied source observations; it does not crawl sites or
claim that a search result snippet proves a competition membership.
"""
from datetime import date
from typing import Literal
from urllib.parse import urlparse
from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/research", tags=["verified-research"])
Squad = Literal["first_team", "u21", "u19", "u17", "futsal", "unknown"]
Status = Literal["official", "secondary", "unverified"]

class Observation(BaseModel):
    statement: str = Field(min_length=5, max_length=1500)
    source_url: str = Field(min_length=8, max_length=2000)
    source_title: str = Field(min_length=3, max_length=300)
    source_status: Status = "unverified"
    squad: Squad = "unknown"
    competition: str | None = Field(default=None, max_length=200)
    season: str | None = Field(default=None, max_length=30)
    observed_on: date | None = None
    club_name_in_source: str | None = Field(default=None, max_length=200)

class ResearchRequest(BaseModel):
    club: str = Field(min_length=2, max_length=200)
    season: str = Field(min_length=4, max_length=30)
    observations: list[Observation] = Field(default_factory=list, max_length=100)

def classify(item: Observation, club: str, season: str):
    parsed = urlparse(item.source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return "rejected", "invalid_source_url"
    if not item.club_name_in_source or item.club_name_in_source.strip().casefold() != club.strip().casefold():
        return "needs_review", "club_identity_not_verified"
    if item.season != season:
        return "needs_review", "season_not_verified"
    if item.squad == "unknown":
        return "needs_review", "squad_not_verified"
    if not item.competition:
        return "needs_review", "competition_not_verified"
    if item.source_status == "unverified":
        return "needs_review", "source_not_verified"
    return "supported", "source_observation_only"

@router.post("/clubs/verify")
def verify_club(request: ResearchRequest):
    groups = {"supported": [], "needs_review": [], "rejected": []}
    for item in request.observations:
        decision, reason = classify(item, request.club, request.season)
        groups[decision].append({
            **item.model_dump(mode="json"),
            "decision": decision,
            "reason": reason,
        })
    return {
        "club": request.club, "season": request.season,
        "verified_live": False,
        "note": "Source observations are not independently fetched or verified by this endpoint.",
        "evidence": groups,
        "first_team": [x for x in groups["supported"] if x["squad"] == "first_team"],
        "u21": [x for x in groups["supported"] if x["squad"] == "u21"],
    }

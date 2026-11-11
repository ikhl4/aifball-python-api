from club_research import Observation, ResearchRequest, verify_club

def test_separates_u21_from_first_team():
    common = dict(source_url="https://example.org/official", source_title="Official schedule",
                  source_status="official", club_name_in_source="التضامن", season="2026/2027",
                  competition="دوري جوي")
    result = verify_club(ResearchRequest(club="التضامن", season="2026/2027", observations=[
        Observation(statement="Participation in U21 league", squad="u21", **common)
    ]))
    assert len(result["u21"]) == 1
    assert result["first_team"] == []
    assert result["verified_live"] is False

def test_rejects_wrong_club_and_season():
    observation = Observation(statement="A club fixture was listed",
        source_url="https://example.org/a", source_title="Fixture list",
        source_status="official", squad="first_team", competition="Fourth division",
        club_name_in_source="نادي آخر", season="2025/2026")
    result = verify_club(ResearchRequest(club="التضامن", season="2026/2027", observations=[observation]))
    assert not result["first_team"]
    assert len(result["evidence"]["needs_review"]) == 1

def test_unverified_snippet_cannot_be_supported():
    observation = Observation(statement="Claim found in a search snippet",
        source_url="https://example.org/a", source_title="Search result",
        source_status="unverified", squad="first_team", competition="Fourth division",
        club_name_in_source="التضامن", season="2026/2027")
    result = verify_club(ResearchRequest(club="التضامن", season="2026/2027", observations=[observation]))
    assert result["evidence"]["supported"] == []

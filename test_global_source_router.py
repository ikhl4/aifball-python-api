from global_source_router import RouteRequest, plan

def test_saudi_sources():
    result = plan(RouteRequest(query="التضامن", country="السعودية", season="2026/2027"))
    assert result["country"] == "SA"
    assert any(x["name"] == "SAFF" for x in result["official_sources"])
    assert result["live_verified"] is False

def test_european_club_does_not_use_saff():
    result = plan(RouteRequest(query="Barcelona", country="Spain", squad="first_team"))
    assert result["country"] == "ES"
    assert any(x["name"] == "LaLiga" for x in result["official_sources"])
    assert not any(x["name"] == "SAFF" for x in result["official_sources"])

def test_unknown_country_does_not_guess():
    result = plan(RouteRequest(query="Unknown club"))
    assert result["country"] is None
    assert result["country_resolved"] is False
    assert all(x["kind"] == "international" for x in result["official_sources"])

def test_youth_scope_preserved():
    result = plan(RouteRequest(query="Al Ittihad", country="SA", squad="u21"))
    assert result["squad"] == "u21"
    assert all(x["status"] == "not_queried" for x in result["statistics_providers"])

def test_new_world_regions():
    for country, club, federation, confed in [
        ("Brazil", "Flamengo", "CBF", "CONMEBOL"),
        ("Argentina", "Boca Juniors", "AFA", "CONMEBOL"),
        ("Japan", "Urawa Red Diamonds", "JFA", "AFC"),
        ("South Africa", "Mamelodi Sundowns", "SAFA", "CAF"),
    ]:
        result = plan(RouteRequest(query=club, country=country, season="2026"))
        names = {item["name"] for item in result["official_sources"]}
        assert federation in names
        assert confed in names
        assert "SAFF" not in names
        assert result["live_verified"] is False

def test_regional_routing_for_existing_countries():
    result = plan(RouteRequest(query="Barcelona", country="Spain"))
    names = {item["name"] for item in result["official_sources"]}
    assert "UEFA" in names
    assert "AFC" not in names

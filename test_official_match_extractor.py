from official_match_extractor import extract_barcelona_results

URL = "https://www.fcbarcelona.com/en/football/first-team/results"

def test_extract_official_candidates():
    text = ("First Team Results November November 2026 "
            "Sun 08 Nov La Liga Matchday 12 Riyadh Air Metropolitano Atlético Madrid 1 - 2 FC Barcelona "
            "Tue 03 Nov UEFA Champions League Matchday 4 Spotify Camp Nou FC Barcelona 3 - 0 Aston Villa "
            "Sat 31 Oct La Liga Matchday 11 Spotify Camp Nou FC Barcelona 6 - 1 Alavés Chevron")
    matches = extract_barcelona_results(text, URL)
    assert len(matches) == 3
    assert [m["date"] for m in matches] == ["2026-11-08", "2026-11-03", "2026-10-31"]
    assert all(m["verification"] == "extracted_unverified" for m in matches)

def test_rejects_unsupported_source_and_squad():
    text = "First Team Results November 2026 Sun 08 Nov La Liga FC Barcelona 2 - 1 Opponent"
    assert extract_barcelona_results(text, "https://example.com") == []
    assert extract_barcelona_results(text, URL, "under_21") == []

def test_rejects_unstructured_or_ambiguous_scores():
    text = "First Team Results November 2026 Sun 08 Nov La Liga FC Barcelona 2 - 1 Opponent 3 - 4 Other"
    assert extract_barcelona_results(text, URL) == []

def test_normalized_teams_and_mojibake():
    text = ("First Team Results November November 2026 Nov 2026 "
            "Sun 08 Nov La Liga Matchday 12 Riyadh Air Metropolitano AtlÃ©tico Madrid 1 - 2 FC Barcelona "
            "Tue 03 Nov UEFA Champions League Matchday 4 Spotify Camp Nou FC Barcelona 3 - 0 Aston Villa "
            "October October 2026 Oct 2026 Sat 31 Oct La Liga Matchday 11 Spotify Camp Nou FC Barcelona 6 - 1 AlavÃ©s Chevron")
    rows = extract_barcelona_results(text, URL)
    assert len(rows) == 3
    assert [(r["home_team"], r["away_team"]) for r in rows] == [
        ("Atlético Madrid", "FC Barcelona"), ("FC Barcelona", "Aston Villa"), ("FC Barcelona", "Alavés")]
    assert rows[2]["date"] == "2026-10-31"
    assert all("context" not in k for row in rows for k in row)

def test_unknown_opponent_not_guessed():
    text = "First Team Results November 2026 Sun 08 Nov La Liga Camp Nou FC Barcelona 2 - 1 Unrecognized Town"
    assert extract_barcelona_results(text, URL) == []


def test_encoding_repair_for_raw_evidence_and_match_facts():
    from official_match_extractor import clean_encoding
    damaged = "Atl" + chr(0xC3) + chr(0xA9) + "tico Madrid, Alav" + chr(0xC3) + chr(0xA9) + "s"
    assert clean_encoding(damaged) == "Atlético Madrid, Alavés"
    text = ("First Team Results November 2026 Sun 08 Nov La Liga "
            "Riyadh Air Metropolitano " + damaged.split(",")[0] + " 1 - 2 FC Barcelona Chevron")
    matches = extract_barcelona_results(text, URL)
    assert len(matches) == 1
    assert matches[0]["home_team"] == "Atlético Madrid"


def test_repair_double_encoded_official_text():
    from official_match_extractor import clean_encoding
    correct = "Atlético Madrid and Alavés"
    twice = correct.encode("utf-8").decode("latin-1").encode("utf-8").decode("latin-1")
    assert clean_encoding(twice) == correct
    assert clean_encoding(correct) == correct
    assert clean_encoding("الهلال") == "الهلال"

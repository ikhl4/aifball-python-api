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

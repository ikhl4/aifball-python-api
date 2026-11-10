from fastapi import HTTPException
from live_official_evidence import fetch_official, club_evidence, VisibleText

def test_reject_untrusted_url():
    try:
        fetch_official("https://example.com/private")
        assert False, "should reject"
    except HTTPException as exc:
        assert exc.status_code == 400

def test_unknown_club_is_not_fabricated():
    result = club_evidence("Unknown football team")
    assert result["status"] == "not_configured"
    assert result["verified_live"] is False

def test_html_visible_text_only():
    p = VisibleText()
    p.feed("<html><script>secret</script><h1>برشلونة</h1><p>2 - 1</p></html>")
    assert "برشلونة" in p.parts
    assert "secret" not in p.parts

def test_official_club_identity(monkeypatch):
    monkeypatch.setattr("live_official_evidence.fetch_official", lambda url: {"status": "ok", "text": "Sample"})
    result = club_evidence("Barcelona")
    assert result["squad"] == "first_team"
    assert result["verified_live"] is False
    assert result["fetch"]["status"] == "ok"

def test_main_content_filters_site_chrome():
    p = VisibleText()
    p.feed("<html><header>Tickets</header><nav>Shop</nav><main><h1>Results</h1><p>Barça</p></main><footer>Privacy</footer></html>")
    assert p.focus_parts == ["Results", "Barça"]
    assert "Tickets" not in p.parts
    assert "Shop" not in p.parts

def test_unknown_match_facts_not_claimed(monkeypatch):
    monkeypatch.setattr("live_official_evidence.fetch_official", lambda url: {
        "status": "ok", "text": "Results", "match_facts": [],
        "match_facts_status": "not_extracted"})
    result = club_evidence("Barcelona")
    assert result["verified_live"] is False
    assert result["fetch"]["match_facts"] == []

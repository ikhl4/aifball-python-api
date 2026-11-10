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

# tests/test_ui.py — Smoke tests for the Web UI routes

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from api.main import app


def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Scenario: Home page (download input)
# ---------------------------------------------------------------------------


def test_home_page_renders():
    """Scenario: GET / renders the download form with input and button."""
    c = client()
    resp = c.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    body = resp.text
    assert "Download" in body  # heading
    assert "target" in body  # input field name
    assert "<form" in body.lower()
    assert "button" in body.lower() or "submit" in body.lower()


def test_home_page_has_htmx():
    """Scenario: the home page loads HTMX."""
    c = client()
    resp = c.get("/")
    assert "htmx" in resp.text.lower() or "hx-" in resp.text.lower()


def test_home_page_has_navbar():
    """Scenario: the page has navigation links to History and Settings."""
    c = client()
    resp = c.get("/")
    assert "/history" in resp.text
    assert "/settings" in resp.text


# ---------------------------------------------------------------------------
# Scenario: History view
# ---------------------------------------------------------------------------


def test_history_page_empty():
    """Scenario: History page renders with no videos."""
    c = client()
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.get_all.return_value = []
        mock_ms_class.return_value = mock_ms
        resp = c.get("/history")
    assert resp.status_code == 200
    assert "History" in resp.text
    assert "No videos" in resp.text or "empty" in resp.text.lower()


def test_history_page_with_videos():
    """Scenario: History page renders video records in a table."""
    c = client()
    records = [
        {"video_id": "v1", "profile": "@u", "status": "downloaded", "url": "https://tiktok.com/@u/video/v1"},
        {"video_id": "v2", "profile": "@u", "status": "downloaded", "url": "https://tiktok.com/@u/video/v2"},
    ]
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.get_all.return_value = records
        mock_ms_class.return_value = mock_ms
        resp = c.get("/history")
    assert resp.status_code == 200
    assert "v1" in resp.text
    assert "v2" in resp.text
    assert "<table" in resp.text.lower()


def test_history_page_pagination():
    """Scenario: History page shows pagination controls when total > page_size."""
    c = client()
    records = [
        {"video_id": f"v{i}", "profile": "@u", "status": "downloaded", "url": f"https://x.com/{i}"}
        for i in range(25)
    ]
    with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
        mock_ms = MagicMock()
        mock_ms.get_all.return_value = records
        mock_ms_class.return_value = mock_ms
        resp = c.get("/history?page=1&page_size=20")
    assert resp.status_code == 200
    assert "Next" in resp.text  # pagination control


# ---------------------------------------------------------------------------
# Scenario: Settings panel
# ---------------------------------------------------------------------------


def test_settings_page_renders():
    """Scenario: GET /settings renders the settings form."""
    c = client()
    resp = c.get("/settings")
    assert resp.status_code == 200
    body = resp.text
    assert "Settings" in body
    assert "proxy_url" in body
    assert "cookie_file" in body
    assert "video_format" in body


def test_settings_page_shows_defaults():
    """Scenario: settings page shows default proxy URL."""
    c = client()
    with patch.dict("os.environ", {"PROXY_URL": "socks5h://custom:9050"}, clear=False):
        resp = c.get("/settings")
    assert resp.status_code == 200
    assert "socks5h://custom:9050" in resp.text


def test_settings_page_save():
    """Scenario: POST /settings persists the values and re-renders."""
    c = client()
    resp = c.post("/settings", data={
        "proxy_url": "socks5h://new:1080",
        "cookie_file": "/tmp/cookies.txt",
        "video_format": "bestvideo",
    })
    assert resp.status_code == 200
    assert "socks5h://new:1080" in resp.text
    assert "/tmp/cookies.txt" in resp.text
    assert "bestvideo" in resp.text


# ---------------------------------------------------------------------------
# Scenario: Responsive design (static assets)
# ---------------------------------------------------------------------------


def test_static_css_served():
    """Scenario: the CSS stylesheet is accessible."""
    c = client()
    resp = c.get("/static/css/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers.get("content-type", "")


def test_static_js_served():
    """Scenario: the HTMX loader JS is accessible."""
    c = client()
    resp = c.get("/static/js/htmx.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers.get("content-type", "").lower() or "text" in resp.headers.get("content-type", "").lower()


def test_css_has_responsive_media_query():
    """Scenario: the CSS includes a @media query for mobile responsiveness."""
    c = client()
    resp = c.get("/static/css/style.css")
    assert "@media" in resp.text
    assert "max-width" in resp.text


# ---------------------------------------------------------------------------
# Scenario: All pages extend base template
# ---------------------------------------------------------------------------


def test_pages_have_html_doctype():
    """Scenario: all rendered pages have valid HTML5 doctype."""
    c = client()
    for path in ["/", "/history", "/settings"]:
        with patch("tiktok_dl.manifest.ManifestStore") as mock_ms_class:
            mock_ms = MagicMock()
            mock_ms.get_all.return_value = []
            mock_ms_class.return_value = mock_ms
            resp = c.get(path)
        assert resp.status_code == 200
        assert resp.text.strip().startswith("<!DOCTYPE html>") or "<!DOCTYPE" in resp.text.upper()
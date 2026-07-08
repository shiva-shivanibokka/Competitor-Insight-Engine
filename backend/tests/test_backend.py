"""Offline unit tests for the pure logic — no network, no API keys needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyzer
import scraper
from analyzer import _is_valid_competitor_url, extract_competitors_from_search
from blocklist import is_blocked
from report import _extract_field, _normalise_url
from searcher import validate_url
from security import BlockedURLError, fetch_validated, is_public_url


# --- SSRF guard (finding #2) ---

def test_ssrf_allows_public():
    assert is_public_url("https://stripe.com")


def test_ssrf_blocks_metadata_and_internal():
    for bad in [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://10.0.0.5",
        "http://192.168.1.1",
        "ftp://example.com",
        "file:///etc/passwd",
    ]:
        assert not is_public_url(bad), bad


def test_validate_url_rejects_blocked_without_network():
    # Blocklist check happens before any network call.
    assert validate_url("https://www.reddit.com/r/startups") is False


class _FakeResp:
    def __init__(self, status, location=None):
        self.status_code = status
        self.headers = {"location": location} if location else {}
        self.is_redirect = location is not None


def test_ssrf_redirect_blocked(monkeypatch):
    # A page that 302-redirects to cloud metadata must NOT be followed.
    def fake_get(url, **kwargs):
        if "169.254.169.254" in url:
            return _FakeResp(200)  # would leak if we ever got here
        return _FakeResp(302, location="http://169.254.169.254/latest/meta-data/")

    monkeypatch.setattr("security.requests.get", fake_get)
    try:
        fetch_validated("https://evil.example.com", headers={}, timeout=(5, 10))
        raised = False
    except BlockedURLError:
        raised = True
    assert raised, "redirect to internal address was not blocked"


# --- Blocklist (finding #8: single source of truth) ---

def test_blocklist():
    assert is_blocked("https://www.reddit.com/r/x")
    assert is_blocked("https://g2.com/products")
    assert not is_blocked("https://adyen.com")
    # F2: substring false-positives — these are legit domains, not blocked sources.
    assert not is_blocked("https://www.netflix.com")  # contains "x.com"
    assert not is_blocked("https://fox.com")


def test_competitor_url_validation():
    assert _is_valid_competitor_url("https://adyen.com", "Stripe")
    assert not _is_valid_competitor_url("https://reddit.com/r/stripe", "Stripe")
    assert not _is_valid_competitor_url("https://stripe.com", "Stripe")  # is the company itself
    assert not _is_valid_competitor_url("not-a-url", "Stripe")


# --- Competitor extraction: dedup + blocklist survive past the LLM ---

def test_extract_competitors_dedups_and_filters(monkeypatch):
    fake_llm_json = """[
        {"name": "Adyen", "url": "https://www.adyen.com"},
        {"name": "Adyen dup", "url": "https://adyen.com/"},
        {"name": "Reddit thread", "url": "https://reddit.com/r/payments"},
        {"name": "Braintree", "url": "https://www.braintreepayments.com"}
    ]"""
    monkeypatch.setattr(analyzer, "llm_call", lambda *a, **k: fake_llm_json)
    out = extract_competitors_from_search("Stripe", "irrelevant", model="claude-haiku-4-5")
    names = [c["name"] for c in out]
    assert "Adyen" in names and "Braintree" in names
    assert "Reddit thread" not in names  # blocklist
    assert len(out) == 2  # adyen deduped by domain


def test_extract_competitors_handles_bad_json(monkeypatch):
    monkeypatch.setattr(analyzer, "llm_call", lambda *a, **k: "not json at all")
    assert extract_competitors_from_search("X", "y", model="claude-haiku-4-5") == []


def test_extract_competitors_ignores_non_dict(monkeypatch):
    # F3: valid JSON array but of strings, not objects — must not crash.
    monkeypatch.setattr(analyzer, "llm_call", lambda *a, **k: '["Adyen", "Square"]')
    assert extract_competitors_from_search("Stripe", "y", model="claude-haiku-4-5") == []


def test_scrape_key_pages_empty_when_no_text(monkeypatch):
    # F4: an all-empty scrape must return "" so the fail-fast guard can fire.
    monkeypatch.setattr(scraper, "scrape_page", lambda url: "")
    assert scraper.scrape_key_pages("https://example.com") == ""


# --- report.py helpers ---

def test_normalise_url_prepends_scheme():
    assert _normalise_url("stripe.com") == "https://stripe.com"
    assert _normalise_url("https://stripe.com") == "https://stripe.com"


def test_extract_field():
    profile = "COMPANY NAME: Stripe\nINDUSTRY: Payments\nPRICING MODEL: usage-based"
    assert _extract_field(profile, "INDUSTRY") == "Payments"
    assert _extract_field(profile, "MISSING") == "technology"  # documented fallback

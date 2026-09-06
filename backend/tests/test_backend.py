"""Offline unit tests for the pure logic — no network, no API keys needed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analyzer
import config
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


def test_competitor_url_matches_whole_labels_not_substrings():
    # The company name used to be tested as a substring of the whole URL, so a
    # short name threw away unrelated companies. Whole-label matching keeps the
    # company's own subdomains rejected without that collateral damage.
    assert _is_valid_competitor_url("https://adaptive.com", "Ada")
    assert _is_valid_competitor_url("https://wisetech.com", "Wise")
    assert not _is_valid_competitor_url("https://www.ada.com", "Ada")
    assert not _is_valid_competitor_url("https://dashboard.stripe.com", "Stripe")


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


# --- temperature: newer models reject it outright ---

class _FakeChoice:
    def __init__(self, text):
        self.message = type("M", (), {"content": text})()


class _FakeCompletions:
    """Stands in for a provider that 400s on `temperature`, as Claude 5 does."""

    def __init__(self, rejects_temperature):
        self.rejects = rejects_temperature
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.rejects and "temperature" in kwargs:
            raise BadRequestError_stub("`temperature` is deprecated for this model.")
        return type("R", (), {"choices": [_FakeChoice("hello")]})()


class BadRequestError_stub(analyzer.BadRequestError):
    def __init__(self, message):
        Exception.__init__(self, message)


def _patch_client(monkeypatch, completions):
    client = type("C", (), {"chat": type("Ch", (), {"completions": completions})()})()
    monkeypatch.setattr(analyzer, "get_client", lambda *a, **k: client)


def test_llm_call_retries_without_temperature_when_rejected(monkeypatch):
    analyzer._REJECTS_TEMPERATURE.discard("claude-sonnet-5")
    completions = _FakeCompletions(rejects_temperature=True)
    _patch_client(monkeypatch, completions)
    monkeypatch.setitem(analyzer.MODEL_TO_PROVIDER, "claude-sonnet-5", "anthropic")

    assert analyzer.llm_call("sys", "user", model="claude-sonnet-5") == "hello"
    assert "temperature" in completions.calls[0]
    assert "temperature" not in completions.calls[1]
    # The second call for the same model skips the doomed attempt entirely.
    assert analyzer.llm_call("sys", "user", model="claude-sonnet-5") == "hello"
    assert len(completions.calls) == 3
    analyzer._REJECTS_TEMPERATURE.discard("claude-sonnet-5")


def test_llm_call_keeps_temperature_when_accepted(monkeypatch):
    completions = _FakeCompletions(rejects_temperature=False)
    _patch_client(monkeypatch, completions)
    assert analyzer.llm_call("sys", "user", model="claude-haiku-4-5", temperature=0.0) == "hello"
    assert completions.calls == [
        {
            "model": "claude-haiku-4-5",
            "messages": [
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "user"},
            ],
            "temperature": 0.0,
        }
    ]


def test_llm_call_does_not_swallow_unrelated_bad_requests(monkeypatch):
    class Always400(_FakeCompletions):
        def create(self, **kwargs):
            raise BadRequestError_stub("context window exceeded")

    _patch_client(monkeypatch, Always400(rejects_temperature=True))
    try:
        analyzer.llm_call("sys", "user", model="claude-haiku-4-5")
        failed = False
    except ValueError as e:
        failed = "context window" in str(e)
    assert failed, "a non-temperature 400 must not be retried away"


# --- model catalogue: config.py is a fallback, the provider is the truth ---

def test_config_models_have_no_duplicate_names():
    # MODEL_TO_PROVIDER is a reverse map, so a name listed under two providers
    # would silently route to whichever came last.
    seen = [m for p in config.PROVIDERS.values() for m in p["models"]]
    assert len(seen) == len(set(seen)), "a model name appears under two providers"


def test_default_models_are_in_the_catalogue():
    for model in (config.DEFAULT_MODEL, config.FAST_MODEL, config.SMART_MODEL):
        assert model in config.MODEL_TO_PROVIDER


def test_list_models_reads_from_the_provider(monkeypatch):
    listed = type("L", (), {"data": [type("M", (), {"id": "b"})(), type("M", (), {"id": "a"})()]})()
    client = type("C", (), {"models": type("Mo", (), {"list": lambda self: listed})()})()
    monkeypatch.setattr(analyzer, "client_for", lambda *a, **k: client)
    assert analyzer.list_models("anthropic", "sk-test") == ["a", "b"]


# --- a caller's bad key is a 422, not a 500 ---

def test_bad_provider_key_is_reported_as_the_callers_problem(monkeypatch):
    # A rejected key used to surface as HTTP 500 with a logged stack trace,
    # which reads as "this service is broken" rather than "fix your key".
    class Rejects:
        def create(self, **kwargs):
            raise RuntimeError("401 invalid x-api-key")

    _patch_client(monkeypatch, Rejects())
    try:
        analyzer.llm_call("sys", "user", model="claude-haiku-4-5")
        raised = None
    except Exception as e:  # noqa: BLE001 - the type under test
        raised = e
    assert isinstance(raised, ValueError), f"expected ValueError, got {type(raised).__name__}"


# --- the API is reachable under both mount points ---

def test_routes_are_served_with_and_without_the_api_prefix():
    # Production routes /api/* to this service and forwards the path unchanged;
    # uvicorn locally and the notebook call the bare paths. Both must work, or
    # the deployment and the local workflow disagree about the same code.
    from fastapi.testclient import TestClient

    from app import app as fastapi_app

    client = TestClient(fastapi_app)
    for prefix in ("", "/api"):
        assert client.get(f"{prefix}/health").json() == {"status": "ok"}
        assert client.get(f"{prefix}/providers").status_code == 200
        rejected = client.post(
            f"{prefix}/report",
            json={
                "company_url": "https://x.com",
                "company_name": "X",
                "provider": "not-a-provider",
                "model": "m",
                "llm_key": "k",
                "tavily_key": "t",
            },
        )
        assert rejected.status_code == 400, prefix


# --- report.py helpers ---

def test_normalise_url_prepends_scheme():
    assert _normalise_url("stripe.com") == "https://stripe.com"
    assert _normalise_url("https://stripe.com") == "https://stripe.com"


def test_extract_field():
    profile = "COMPANY NAME: Stripe\nINDUSTRY: Payments\nPRICING MODEL: usage-based"
    assert _extract_field(profile, "INDUSTRY") == "Payments"
    assert _extract_field(profile, "MISSING") == "technology"  # documented fallback

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


def test_reachability_checks_do_not_follow_redirect_chains():
    """`timeout` is per hop, so following 30 of them is 30x the stated budget.

    A reachability pre-check that can take four minutes is worse than no
    pre-check: it burns the request budget the actual work needs. A 3xx already
    proves the host answered, and scrape_page follows the chain safely later.
    """
    import report as report_mod
    import searcher as searcher_mod

    calls = []

    def fake_head(url, **kwargs):
        calls.append(kwargs)
        return _FakeResp(301, location="https://elsewhere.example.com/")

    original_search, original_report = searcher_mod.requests.head, report_mod.requests.head
    searcher_mod.requests.head = fake_head
    report_mod.requests.head = fake_head
    try:
        assert searcher_mod.validate_url("https://stripe.com") is True
        assert report_mod._check_url_reachable("https://stripe.com") is True
    finally:
        searcher_mod.requests.head = original_search
        report_mod.requests.head = original_report

    assert len(calls) == 2
    for kwargs in calls:
        assert kwargs["allow_redirects"] is False, "a redirect chain can outlast the request budget"


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


# --- the committed recording must never carry a key ---

DEMO_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo"


def _recordings():
    return sorted(p for p in DEMO_DIR.glob("*.json") if p.name != "index.json")


def test_secret_pattern_catches_keys_without_crying_wolf():
    """The scrubber is only useful if it is both sensitive and specific.

    It was neither at first: it matched `sk-` plus any eight characters, so the
    phrase "task-execution" in a generated report tripped it. A scanner that
    fires on ordinary prose is one that gets switched off, which leaves nothing
    guarding the committed recordings.
    """
    from record_demo import SECRET

    for real in [
        "sk-ant-api03-" + "a1B2c3D4e5" * 4,
        "sk-proj-" + "Xy9" * 12,
        "sk-" + "a1B2c3D4e5" * 5,
        "tvly-dev-" + "abc123XYZ" * 3,
        "gsk_" + "Ab3" * 12,
        "AIza" + "Bc4" * 12,
    ]:
        assert SECRET.search(real), f"a real-shaped key was not caught: {real[:14]}..."

    for prose in [
        "the narrative from advisory AI to autonomous task-execution AI",
        "a risk-execution tradeoff",
        "disk-encryption at rest",
        "ask-me-anything sessions",
        "gsk_short",
        "sk-tooshort",
    ]:
        assert not SECRET.search(prose), f"false positive on ordinary prose: {prose!r}"


def test_recorded_runs_are_well_formed_and_secret_free():
    """Each replay is a real run's output committed as a static file.

    That makes these the artifacts in this repo most able to publish a key by
    accident, and the ones nobody would think to re-read before shipping. If
    none are committed the replay tab says so, which is fine; any that are
    present have to be clean.
    """
    import json

    from record_demo import SECRET

    for path in _recordings():
        raw = path.read_text(encoding="utf-8")
        found = SECRET.findall(raw)
        assert not found, f"key-shaped string in {path.name}: {found[:1]}"

        d = json.loads(raw)
        for field in ("recorded_at", "company", "duration_seconds", "smart_model", "frames", "report"):
            assert field in d, f"{path.name} is missing {field}"
        assert d["frames"], f"{path.name} has no frames and would replay as a blank panel"
        assert d["report"].strip(), f"{path.name} has no report to show at the end"
        # Timestamps drive the playback delays; unsorted ones produce negative gaps.
        times = [f["t"] for f in d["frames"]]
        assert times == sorted(times), f"{path.name} frame timestamps are not monotonic"


def test_demo_index_matches_the_recordings_on_disk():
    """The picker is built from index.json, so a stale index is a dead button.

    index.json is generated (`record_demo.py --index-only`), which is exactly
    why it can drift: deleting a recording without regenerating leaves an entry
    pointing at a file that 404s.
    """
    import json

    index = DEMO_DIR / "index.json"
    recordings = _recordings()
    if not recordings:
        return

    assert index.is_file(), "recordings exist but index.json does not; the picker would be empty"
    listed = {r["slug"] for r in json.loads(index.read_text(encoding="utf-8"))["runs"]}
    on_disk = {p.stem for p in recordings}
    assert listed == on_disk, f"index.json lists {listed}, disk has {on_disk}"


# --- report.py helpers ---

def test_normalise_url_prepends_scheme():
    assert _normalise_url("stripe.com") == "https://stripe.com"
    assert _normalise_url("https://stripe.com") == "https://stripe.com"


def test_extract_field():
    profile = "COMPANY NAME: Stripe\nINDUSTRY: Payments\nPRICING MODEL: usage-based"
    assert _extract_field(profile, "INDUSTRY") == "Payments"
    assert _extract_field(profile, "MISSING") == "technology"  # documented fallback

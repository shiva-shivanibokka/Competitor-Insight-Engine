"""Offline tests for the eval LLM transport: cost ledger, hard cap, retries,
crash/resume, model pinning, and exact replay of the committed Groq run.
No network: the Anthropic client is a fake, and sleeps are recorded, not slept."""

import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import common  # noqa: E402
from common import PROVIDERS, CallFailed, CapReached, LLMShim  # noqa: E402

SYS, USER = "system prompt", "user prompt " * 50


def _resp(inp=1000, out=200, text="[]", model="claude-haiku-4-5-20251001"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], model=model,
                           stop_reason="end_turn", usage=SimpleNamespace(input_tokens=inp, output_tokens=out))


def _err(cls, status, headers=None):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx.Response(status, request=req, headers=headers or {}), body=None)


class FakeClient:
    def __init__(self, script):
        self.script = list(script)  # items: response objects or exceptions
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def prov(tmp_path):
    return replace(PROVIDERS["anthropic"], cache=tmp_path / "cache.jsonl", ledger=tmp_path / "ledger.jsonl")


def test_records_usage_cost_and_model(prov):
    fake = FakeClient([_resp(1000, 200)])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    assert s(SYS, USER, model=prov.model, temperature=0.0) == "[]"
    led = [json.loads(x) for x in prov.ledger.read_text().splitlines()]
    assert [r["type"] for r in led] == ["reserve", "settle"]          # reserved before, settled after
    assert led[0]["cost_usd"] == pytest.approx(s.worst_case(SYS, USER))
    assert led[1]["cost_usd"] == pytest.approx(1000 * 1e-6 + 200 * 5e-6)
    assert led[1]["model_reported"] == "claude-haiku-4-5-20251001"
    assert s.spent() == pytest.approx(1000 * 1e-6 + 200 * 5e-6)
    kw = fake.calls[0]
    assert kw["model"] == "claude-haiku-4-5-20251001"
    assert "seed" not in kw and "reasoning_effort" not in kw
    assert kw["temperature"] == 0.0


def test_cache_hit_makes_no_call(prov):
    fake = FakeClient([_resp()])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    s(SYS, USER, temperature=0.0)
    s(SYS, USER, temperature=0.0)
    assert len(fake.calls) == 1


def test_429_honours_retry_after_then_succeeds(prov):
    slept = []
    fake = FakeClient([_err(anthropic.RateLimitError, 429, {"retry-after": "7"}), _resp()])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=slept.append)
    s(SYS, USER, temperature=0.0)
    assert slept == [8.0] and len(fake.calls) == 2


def test_429_gives_up_after_three_attempts(prov):
    fake = FakeClient([_err(anthropic.RateLimitError, 429)] * 5)
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    with pytest.raises(CallFailed):
        s(SYS, USER, temperature=0.0)
    assert len(fake.calls) == 3
    assert s.spent() == 0  # 429s are refusals, settled at $0


@pytest.mark.parametrize("cls,status", [(anthropic.BadRequestError, 400), (anthropic.AuthenticationError, 401),
                                        (anthropic.PermissionDeniedError, 403), (anthropic.NotFoundError, 404)])
def test_4xx_fails_fast_without_retry(prov, cls, status):
    fake = FakeClient([_err(cls, status), _resp()])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    with pytest.raises(CallFailed):
        s(SYS, USER, temperature=0.0)
    assert len(fake.calls) == 1


def test_cap_refuses_before_calling(prov):
    fake = FakeClient([_resp(1000, 200)] * 10)
    s = LLMShim(prov, cap=0.006, client=fake, sleep=lambda x: None)
    s(SYS, USER + "a", temperature=0.0)  # spends $0.002
    with pytest.raises(CapReached):       # $0.002 + worst case (~$0.0036) > $0.006? -> next one refused
        s(SYS, USER + "b", temperature=0.0)
        s(SYS, USER + "c", temperature=0.0)
    assert s.spent() <= 0.006


def _committed_prompts():
    """(system, user, real prompt_tokens) for all 188 cached Groq calls of the committed run."""
    import analyzer
    import run_discovery as rd

    shim = common.shim
    ret = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (HERE / "raw" / "retrieval").glob("*.json")}
    out = []
    for r in (json.loads(x) for x in (HERE / "raw" / "discovery.jsonl").read_text(encoding="utf-8").splitlines()):
        system = rd.prompt_for(r["cond"])
        user = (f"The company being researched is: {r['name']}\n\n"
                f"Search results:\n\n{rd.content_for(r['cond'], r['id'], ret, r.get('evidence_from'))}")
        shim.seed = r["seed"]
        out.append((system, user, shim.cache[shim.key(system, user, r["temperature"])]["prompt_tokens"]))
    for rr in ret.values():
        if rr["profile"]:
            user = f"Extract the company profile from this website content:\n\n{rr['scraped']}"
            shim.seed = 0
            out.append((analyzer.EXTRACTION_SYSTEM_PROMPT, user,
                        shim.cache[shim.key(analyzer.EXTRACTION_SYSTEM_PROMPT, user, 0.2)]["prompt_tokens"]))
    shim.seed = 0
    return out


def test_estimate_is_above_real_token_counts():
    """Checked against the 188 real prompt_token counts Groq reported for this run's
    exact prompts (Qwen tokenizer; a proxy for Claude's, which these files cannot measure)."""
    rows = _committed_prompts()
    assert len(rows) == 188
    ratios = sorted(common.est_input_tokens(sy, us) / real for sy, us, real in rows)
    assert ratios[0] >= 1.0, f"estimate below the real count for {sum(r < 1 for r in ratios)} prompts, min {ratios[0]:.3f}"


def test_crash_and_resume_keeps_ledger_and_cache(prov):
    s1 = LLMShim(prov, cap=1.0, client=FakeClient([_resp(500, 100)]), sleep=lambda x: None)
    s1(SYS, USER, temperature=0.0)
    # "crash": s1 never closes, so its lock file is left behind and blocks a second process
    with pytest.raises(common.LedgerLocked):
        LLMShim(prov, cap=1.0, client=FakeClient([]), sleep=lambda x: None)
    s1._lock_path.unlink()  # what the operator does after confirming nothing is running
    s1._lock_path = None
    fake = FakeClient([_resp(500, 100)])
    s2 = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    assert s2.spent() == pytest.approx(500e-6 + 100 * 5e-6)
    s2(SYS, USER, temperature=0.0)  # replayed from cache
    assert fake.calls == []


def test_model_argument_is_respected(prov):
    s = LLMShim(prov, cap=1.0, client=FakeClient([_resp()]), sleep=lambda x: None)
    with pytest.raises(ValueError):
        s(SYS, USER, model="claude-sonnet-5")


def test_committed_groq_run_replays_exactly_from_cache():
    """Every committed discovery record is reproduced from the cache, with no network."""
    import analyzer
    import run_discovery as rd

    shim = common.shim
    assert shim.p.name == "groq"

    def no_network(*a, **k):
        raise AssertionError("replay test tried to call an API")

    # even if EVAL_KEY_* / EVAL_GROQ_* are set in the environment, nothing can be sent
    shim._send_groq = shim._send_anthropic = no_network
    ret = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (HERE / "raw" / "retrieval").glob("*.json")}
    recs = [json.loads(x) for x in (HERE / "raw" / "discovery.jsonl").read_text(encoding="utf-8").splitlines()]
    calls_before = shim.calls_made
    for r in recs:
        content = rd.content_for(r["cond"], r["id"], ret, r.get("evidence_from"))
        analyzer.COMPETITOR_EXTRACTION_PROMPT = rd.prompt_for(r["cond"])
        shim.seed, shim.force_temperature = r["seed"], r["temperature"]
        try:
            preds = analyzer.extract_competitors_from_search(r["name"], content, model=common.MODEL)
        finally:
            shim.force_temperature = None
        assert preds == r["predictions"], r["id"]
    assert shim.calls_made == calls_before


# ---------------------------------------------------------------- round-2 review: spend safety
def _timeout():
    return anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def test_timed_out_attempts_stay_charged_at_worst_case(prov):
    # the server may have billed a request whose response the client never saw
    fake = FakeClient([_timeout(), _timeout(), _resp(1000, 200)])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    s(SYS, USER, temperature=0.0)
    worst = s.worst_case(SYS, USER)
    assert s.spent() == pytest.approx(2 * worst + 1000e-6 + 200 * 5e-6)
    s.close()  # a resumed process re-reads the same total from disk
    assert common.ledger_total(prov.ledger) == pytest.approx(s.spent())


def test_cap_is_rechecked_before_every_attempt(prov):
    fake = FakeClient([_timeout()] * 3)
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    s.cap = s.worst_case(SYS, USER) * 1.5  # room for one attempt, not two
    with pytest.raises(CapReached):
        s(SYS, USER, temperature=0.0)
    assert len(fake.calls) == 1
    assert s.spent() <= s.cap


def test_interrupt_mid_request_stays_charged(prov):
    fake = FakeClient([KeyboardInterrupt()])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    with pytest.raises(KeyboardInterrupt):
        s(SYS, USER, temperature=0.0)
    assert s.spent() == pytest.approx(s.worst_case(SYS, USER))


def test_second_process_cannot_open_the_same_ledger(prov):
    s = LLMShim(prov, cap=1.0, client=FakeClient([]), sleep=lambda x: None)
    with pytest.raises(common.LedgerLocked):
        LLMShim(prov, cap=1.0, client=FakeClient([]), sleep=lambda x: None)
    s.close()
    LLMShim(prov, cap=1.0, client=FakeClient([]), sleep=lambda x: None).close()  # free again after close


def test_estimate_counts_utf8_bytes():
    text = "日本語" * 300  # 900 chars, 2700 UTF-8 bytes
    assert common.est_input_tokens(text) >= len(text.encode("utf-8")) // 2


def test_rejected_requests_are_settled_at_zero(prov):
    fake = FakeClient([_err(anthropic.RateLimitError, 429), _err(anthropic.BadRequestError, 400)])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    with pytest.raises(CallFailed):
        s(SYS, USER, temperature=0.0)
    assert s.spent() == 0


def test_client_base_url_is_pinned(prov, monkeypatch):
    monkeypatch.setattr(common, "_api_key", lambda: "sk-ant-test-not-a-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil.example")
    s = LLMShim(prov, cap=1.0, sleep=lambda x: None)
    assert str(s._client_anthropic().base_url).rstrip("/") == "https://api.anthropic.com"
    s.close()


@pytest.mark.parametrize("cls,status", [(anthropic._exceptions.OverloadedError, 529),
                                        (anthropic._exceptions.ServiceUnavailableError, 503),
                                        (anthropic.InternalServerError, 500)])
def test_5xx_including_529_retries_and_stays_charged(prov, cls, status):
    fake = FakeClient([_err(cls, status), _resp(1000, 200)])
    s = LLMShim(prov, cap=1.0, client=fake, sleep=lambda x: None)
    s(SYS, USER, temperature=0.0)
    assert len(fake.calls) == 2
    assert s.spent() == pytest.approx(s.worst_case(SYS, USER) + 1000e-6 + 200 * 5e-6)


# ---------------------------------------------------------------- round-3: shared user-level spend state
def test_paid_state_lives_in_one_user_level_dir_outside_the_repo():
    import os

    expected = Path(os.environ["LOCALAPPDATA"]) / "sop_eval" / "competitor_insight"
    p = PROVIDERS["anthropic"]
    assert common.STATE_DIR == expected
    assert p.ledger.parent == expected and p.cache.parent == expected
    assert HERE.parent not in p.ledger.parents  # a worktree and the main checkout share one record


def _write_lock(prov, pid):
    lock = prov.ledger.with_suffix(prov.ledger.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(f"pid {pid} 2026-01-01 00:00:00\n")
    return lock


def test_stale_lock_is_reported_as_stale_and_left_for_manual_recovery(prov):
    import psutil

    dead = max(psutil.pids()) + 100_000
    lock = _write_lock(prov, dead)
    with pytest.raises(common.LedgerLocked, match=r"pid \d+ is not running"):
        LLMShim(prov, cap=1.0, client=FakeClient([]), sleep=lambda x: None)
    assert lock.exists()  # recovery stays manual


def test_live_lock_is_reported_as_live(prov):
    import os

    _write_lock(prov, os.getpid())
    with pytest.raises(common.LedgerLocked, match=r"pid \d+ is running"):
        LLMShim(prov, cap=1.0, client=FakeClient([]), sleep=lambda x: None)

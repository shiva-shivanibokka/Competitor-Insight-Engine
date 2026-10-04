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
        if isinstance(item, Exception):
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
    assert led[0]["cost_usd"] == pytest.approx(1000 * 1e-6 + 200 * 5e-6)
    assert led[0]["model_reported"] == "claude-haiku-4-5-20251001"
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
    assert not prov.ledger.exists()


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


def test_worst_case_bounds_actual_cost(prov):
    # the projection must never be below what a call can actually cost
    s = LLMShim(prov, cap=1.0, client=FakeClient([]), sleep=lambda x: None)
    text = "word " * 2000
    worst = s.worst_case(SYS, text)
    max_real = (len(SYS + text) // 3) * prov.price_in + prov.max_tokens * prov.price_out
    assert worst >= max_real


def test_crash_and_resume_keeps_ledger_and_cache(prov):
    s1 = LLMShim(prov, cap=1.0, client=FakeClient([_resp(500, 100)]), sleep=lambda x: None)
    s1(SYS, USER, temperature=0.0)
    del s1  # "crash"
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
    shim._client = object()  # any network attempt would fail loudly
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

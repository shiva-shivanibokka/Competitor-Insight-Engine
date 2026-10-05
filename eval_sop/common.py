"""Shared helpers for the SOP evaluation.

Imports the product's own code from ../backend so the prompts, JSON parsing,
blocklist filtering and dedup being evaluated are exactly the shipped ones.
The only thing replaced is the transport inside analyzer.llm_call (see
LLMShim). System prompt, user prompt and temperature are what the product
passes.

Provider is chosen with EVAL_PROVIDER (one model per provider, never mixed):

  groq       qwen/qwen3.8-27b, Groq free tier, reasoning_effort="none", seed sent.
             Cache raw/llm_cache.jsonl (the committed seed-0 run).
  anthropic  claude-haiku-4-5-20251001 (pinned), official `anthropic` SDK,
             no seed / reasoning params. Cache, cost ledger and lock live in
             %LOCALAPPDATA%/sop_eval/competitor_insight/ (STATE_DIR, outside the repo):
             llm_cache_haiku.jsonl, cost_ledger_haiku.jsonl (+ .lock); hard cap EVAL_COST_CAP
             (default $2.75) at $1/M input and $5/M output tokens.

Every response is cached; re-running replays the cache with zero API calls.
The API key is read in-process from the .env file named by EVAL_KEY_ENV
(variable EVAL_KEY_VAR). It is never printed or written.
"""

import atexit
import collections
import hashlib
import json
import math
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND))

import analyzer  # noqa: E402  (product code)


@dataclass(frozen=True)
class Provider:
    name: str
    model: str
    cache: Path
    ledger: Path | None          # None = free tier, no cost accounting
    price_in: float = 0.0        # $ per input token
    price_out: float = 0.0       # $ per output token
    max_tokens: int = 700


# Paid-run state (cost ledger, its lock, response cache) lives in ONE fixed user-level
# directory outside the repo, so a run from a worktree and a run from the main checkout
# share a single spend record. Deliberately no env override; tests monkeypatch paths.
STATE_DIR = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "sop_eval" / "competitor_insight"

PROVIDERS = {
    "groq": Provider("groq", "qwen/qwen3.8-27b", ROOT / "raw" / "llm_cache.jsonl", None),
    "anthropic": Provider("anthropic", "claude-haiku-4-5-20251001", STATE_DIR / "llm_cache_haiku.jsonl",
                          STATE_DIR / "cost_ledger_haiku.jsonl", price_in=1.0e-6, price_out=5.0e-6),
}
PROVIDER = PROVIDERS[os.environ.get("EVAL_PROVIDER", "groq")]
MODEL = PROVIDER.model
# Hard ceiling for this project, whatever EVAL_COST_CAP says. The prepared paid
# run's worst case is $1.19, and $2.75 is this project's share of the budget, so
# nothing legitimate needs more. Raising it is a deliberate source change.
PROJECT_HARD_MAX_USD = 2.75


def check_cap(cap_usd) -> float:
    """A cap must be a finite, positive number of dollars, no greater than the
    project hard max. This is a function rather than a bare `cap > MAX` guard
    because `nan` fails EVERY comparison: `EVAL_COST_CAP=nan` passed such a
    guard, and then every `spent + worst > cap` was False too — a paid run with
    no cap at all. Accepts strings, so it also works as argparse's `type=`."""
    cap_usd = float(cap_usd)
    if not math.isfinite(cap_usd) or cap_usd <= 0:
        raise ValueError(f"cap {cap_usd!r} must be a finite positive number of dollars")
    if cap_usd > PROJECT_HARD_MAX_USD:
        raise ValueError(f"cap ${cap_usd} exceeds this project's hard max ${PROJECT_HARD_MAX_USD}")
    return cap_usd


def cap_from_env() -> float:
    """EVAL_COST_CAP may only LOWER the cap; anything else raises ValueError."""
    return check_cap(os.environ.get("EVAL_COST_CAP", PROJECT_HARD_MAX_USD))


DEFAULT_CAP = cap_from_env()
MAX_ATTEMPTS = 3          # total attempts per call, including the first
GROQ_TPM_BUDGET = 7000    # Groq free tier reported 8000 tokens/minute


class CapReached(RuntimeError):
    """Refused before calling: the projected worst case would exceed the cost cap."""


class CallFailed(RuntimeError):
    """Non-retryable error (a 4xx other than 429), or 3 attempts exhausted (429 / 5xx incl. 529 / network)."""


class LedgerLocked(RuntimeError):
    """Another process (or a crashed one) holds the ledger lock file."""


def est_input_tokens(*texts: str) -> int:
    """Deliberately high estimate: max(chars, UTF-8 bytes)/2 plus 50 (English is ~4 chars/token).
    /3 under-estimated 1 of the 188 real prompts of this run (ratio 0.84); /2 clears all (min 1.25).
    Checked against those real token counts in tests/test_transport.py."""
    chars = sum(len(t) for t in texts)
    nbytes = sum(len(t.encode("utf-8")) for t in texts)
    return max(chars, nbytes) // 2 + 50


def _lock_holder_status(lock: Path) -> str:
    """Describe the process named in a lock file. Never deletes anything."""
    try:
        pid = int(lock.read_text(encoding="utf-8").split()[1])
    except (OSError, IndexError, ValueError):
        return "the lock file is unreadable, so its owner is unknown."
    try:
        import psutil
    except ImportError:
        return f"pid {pid} holds it (liveness unknown: psutil not installed)."
    if psutil.pid_exists(pid):
        return f"pid {pid} is running (another eval process is probably using this ledger)."
    return f"pid {pid} is not running: the lock is stale (a previous run crashed or was killed)."


def ledger_total(path: Path) -> float:
    """Spend implied by a ledger file. Rows are append-only events: a 'reserve' row
    charges the worst case before a request is sent; a 'settle' row with the same
    rid replaces it with the actual cost (0 for requests the API refused). A
    reservation that is never settled (timeout, crash, Ctrl-C) stays charged."""
    cost: dict[str, float] = {}
    for r in _read_jsonl(path):
        if r["type"] == "reserve":
            cost.setdefault(r["rid"], r["cost_usd"])
        elif r["type"] == "settle":
            cost[r["rid"]] = r["cost_usd"]
    return sum(cost.values())


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _api_key() -> str:
    from dotenv import dotenv_values

    env = os.environ.get("EVAL_KEY_ENV") or os.environ.get("EVAL_GROQ_ENV")
    var = os.environ.get("EVAL_KEY_VAR") or os.environ.get("EVAL_GROQ_VAR")
    if not env or not var:
        raise SystemExit("set EVAL_KEY_ENV/EVAL_KEY_VAR (cache-only replay works without a key)")
    key = dotenv_values(env).get(var)
    if not key:
        raise SystemExit(f"{var} not found in EVAL_KEY_ENV")
    return key


class LLMShim:
    """Replacement for analyzer.llm_call. Set .seed / .tag / .force_temperature before a call."""

    def __init__(self, provider: Provider, cap: float = DEFAULT_CAP, client=None, sleep=time.sleep):
        self.p = provider
        self.cap = check_cap(cap)
        self.seed = 0
        self.tag = ""
        self.force_temperature: float | None = None
        self.calls_made = 0
        self._client = client          # injected fake in tests
        self._sleep = sleep
        self._recent: collections.deque = collections.deque()
        self._lock_path = None
        if provider.ledger is not None:
            self._acquire_lock(provider.ledger.with_suffix(provider.ledger.suffix + ".lock"))
        self.cache = {r["key"]: r for r in _read_jsonl(provider.cache)}
        self._spent = ledger_total(provider.ledger) if provider.ledger else 0.0

    # ------------------------------------------------------------------ lock
    def _acquire_lock(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LedgerLocked(f"{path} exists: {_lock_holder_status(path)} "
                               f"Recovery is manual: confirm no eval run is in progress, "
                               f"then delete the lock file yourself.") from None
        os.write(fd, f"pid {os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode())
        os.close(fd)
        self._lock_path = path
        atexit.register(self.close)

    def close(self) -> None:
        if self._lock_path is not None:
            try:
                self._lock_path.unlink()
            except FileNotFoundError:
                pass
            self._lock_path = None

    # ------------------------------------------------------------- accounting
    def spent(self) -> float:
        return self._spent

    def _ledger_write(self, row: dict) -> None:
        with self.p.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _reserve(self, worst: float) -> str:
        if self._spent + worst > self.cap:
            raise CapReached(f"spent ${self._spent:.4f}; worst case after this attempt "
                             f"${self._spent + worst:.4f} > cap ${self.cap:.2f}")
        rid = uuid.uuid4().hex
        self._ledger_write({"rid": rid, "type": "reserve", "key": self._cur_key, "tag": self.tag,
                            "cost_usd": round(worst, 8), "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self._spent += worst
        return rid

    def _settle(self, rid: str, reserved: float, actual: float, **info) -> None:
        self._ledger_write({"rid": rid, "type": "settle", "cost_usd": round(actual, 8), **info,
                            "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self._spent += actual - reserved

    def worst_case(self, system: str, user: str) -> float:
        return est_input_tokens(system, user) * self.p.price_in + self.p.max_tokens * self.p.price_out

    def key(self, system: str, user: str, temperature: float) -> str:
        h = hashlib.sha256()
        if self.p.name == "groq":  # unchanged from the committed run so its cache replays
            parts = (self.p.model, system, user, repr(float(temperature)), str(self.seed), str(self.p.max_tokens))
        else:
            parts = (self.p.name, self.p.model, system, user, repr(float(temperature)), str(self.p.max_tokens))
        for part in parts:
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        return h.hexdigest()

    # ------------------------------------------------------------------ call
    def __call__(self, system_prompt, user_prompt, model=None, temperature=0.2, api_keys=None):
        if model not in (None, self.p.model):
            raise ValueError(f"shim is pinned to {self.p.model!r}; caller asked for {model!r}")
        if self.force_temperature is not None:
            temperature = self.force_temperature
        k = self.key(system_prompt, user_prompt, temperature)
        if k in self.cache:
            return self.cache[k]["response"]
        self._cur_key = k
        send = self._send_anthropic if self.p.name == "anthropic" else self._send_groq
        rec = send(system_prompt, user_prompt, temperature)
        rec.update({"key": k, "tag": self.tag, "model": self.p.model, "temperature": temperature,
                    "max_tokens": self.p.max_tokens, "called_at": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.cache[k] = rec
        with self.p.cache.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.calls_made += 1
        return rec["response"]

    # ------------------------------------------------------------- anthropic
    def _client_anthropic(self):
        if self._client is None:
            import anthropic

            # base_url pinned so an ANTHROPIC_BASE_URL in the environment cannot redirect the key
            self._client = anthropic.Anthropic(api_key=_api_key(), base_url="https://api.anthropic.com",
                                               max_retries=0, timeout=120.0)
        return self._client

    def _send_anthropic(self, system, user, temperature):
        """Every attempt reserves its worst case in the ledger BEFORE the request (cap
        re-checked each time). Only a response with usage, or an explicit refusal
        that is not billed (429 / other 4xx), settles the row; timeouts, connection
        errors, 5xx and interrupts leave it charged at the worst case."""
        import anthropic

        client = self._client_anthropic()
        worst = self.worst_case(system, user)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            rid = self._reserve(worst)
            t = time.time()
            try:
                resp = client.messages.create(
                    model=self.p.model, max_tokens=self.p.max_tokens, temperature=temperature,
                    system=system, messages=[{"role": "user", "content": user}],
                )
            except anthropic.RateLimitError as e:  # rejected before processing: not billed
                self._settle(rid, worst, 0.0, outcome="429")
                wait = float(e.response.headers.get("retry-after", "20") or 20)
                self._retry_or_fail(attempt, f"429 rate limited; retry-after {wait}s", wait)
                continue
            except anthropic.APIStatusError as e:
                # 5xx: 500 InternalServerError, 503, and 529 OverloadedError (a direct
                # APIStatusError subclass in SDK 0.93, NOT an InternalServerError):
                # retry, and the attempt stays charged at the worst case.
                if e.status_code >= 500:
                    self._retry_or_fail(attempt, f"{e.status_code} {type(e).__name__}", 10)
                    continue
                self._settle(rid, worst, 0.0, outcome=str(e.status_code))  # other 4xx: fail fast
                raise CallFailed(f"{e.status_code} {type(e).__name__}: {str(e)[:200]}") from e
            except anthropic.APIConnectionError as e:  # includes timeouts: may have been billed
                self._retry_or_fail(attempt, f"connection error {type(e).__name__}", 10)
                continue
            actual = resp.usage.input_tokens * self.p.price_in + resp.usage.output_tokens * self.p.price_out
            self._settle(rid, worst, actual, outcome="ok", model_reported=resp.model,
                         input_tokens=resp.usage.input_tokens, output_tokens=resp.usage.output_tokens,
                         stop_reason=resp.stop_reason)
            text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
            return {"model_reported": resp.model, "stop_reason": resp.stop_reason,
                    "prompt_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens,
                    "cost_usd": round(actual, 8), "wall_s": round(time.time() - t, 2), "response": text}
        raise CallFailed("unreachable")

    # ------------------------------------------------------------------ groq
    def _send_groq(self, system, user, temperature):
        import requests

        body = {"model": self.p.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature, "seed": self.seed, "max_tokens": self.p.max_tokens,
                "reasoning_effort": "none"}
        est = est_input_tokens(system, user) + self.p.max_tokens // 2
        key = _api_key()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._pace(est)
            t = time.time()
            try:
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
            except requests.RequestException as e:
                self._retry_or_fail(attempt, f"network error {type(e).__name__}", 15)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                self._retry_or_fail(attempt, f"{r.status_code}", float(r.headers.get("retry-after", "20") or 20))
                continue
            if r.status_code >= 400:
                raise CallFailed(f"{r.status_code}: {r.text[:200]}")
            d = r.json()
            usage = d.get("usage", {})
            self._recent.append((time.time(), usage.get("total_tokens", est)))
            return {"model_reported": d.get("model"), "system_fingerprint": d.get("system_fingerprint"),
                    "seed": self.seed, "prompt_tokens": usage.get("prompt_tokens"),
                    "output_tokens": usage.get("completion_tokens"),
                    "finish_reason": d["choices"][0].get("finish_reason"),
                    "ratelimit_remaining_requests": r.headers.get("x-ratelimit-remaining-requests"),
                    "wall_s": round(time.time() - t, 2),
                    "response": d["choices"][0]["message"].get("content") or ""}
        raise CallFailed("unreachable")

    def _pace(self, est: int) -> None:
        while True:
            now = time.time()
            while self._recent and now - self._recent[0][0] > 60:
                self._recent.popleft()
            if not self._recent or sum(t for _, t in self._recent) + est <= GROQ_TPM_BUDGET:
                return
            self._sleep(2)

    def _retry_or_fail(self, attempt: int, why: str, wait: float) -> None:
        if attempt >= MAX_ATTEMPTS:
            raise CallFailed(f"giving up after {attempt} attempts: {why}")
        print(f"    [{self.p.name}] attempt {attempt}/{MAX_ATTEMPTS}: {why}", flush=True)
        self._sleep(wait + 1)


shim = LLMShim(PROVIDER)


def install_shim(shim=shim):
    """Point the product's transport at the shim. Call this from an entry point,
    NOT at import: when backend/tests and eval_sop/tests are collected in one
    pytest process they share sys.modules["analyzer"], so patching at import
    leaked the shim into the product's own llm_call tests."""
    analyzer.llm_call = shim
    return shim


def load_companies() -> list[dict]:
    return json.loads((ROOT / "ground_truth" / "companies.json").read_text(encoding="utf-8"))

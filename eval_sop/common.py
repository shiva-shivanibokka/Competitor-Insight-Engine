"""Shared helpers for the SOP evaluation.

Imports the product's own code from ../backend so the prompts, JSON parsing,
blocklist filtering and dedup being evaluated are exactly the shipped ones.
The only thing replaced is the transport inside analyzer.llm_call: calls go to
Groq's free tier (OpenAI-compatible endpoint) for ONE model,
qwen/qwen3.8-27b, with Qwen "thinking" disabled (reasoning_effort="none") so
the model answers directly as the product expects. The system prompt, user
prompt and temperature are exactly what the product passes. Every response is
cached in raw/llm_cache.jsonl, so re-running the scripts replays the cache and
makes zero API calls.

Key: GROQ key read in-process from a .env file given by EVAL_GROQ_ENV
(variable name EVAL_GROQ_VAR). Never printed, never written.
"""

import collections
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT.parent / "backend"
sys.path.insert(0, str(BACKEND))

import analyzer  # noqa: E402  (product code)

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "qwen/qwen3.8-27b"
MAX_TOKENS = 700
TPM_BUDGET = 7000  # free tier reported x-ratelimit-limit-tokens: 8000 per minute
CACHE = ROOT / "raw" / "llm_cache.jsonl"

_cache: dict[str, dict] = {}
if CACHE.exists():
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            _cache[rec["key"]] = rec

_recent: collections.deque = collections.deque()  # (time, tokens) for the last 60 s


class BillingRequired(RuntimeError):
    pass


def _key(system: str, user: str, temperature: float, seed: int) -> str:
    h = hashlib.sha256()
    for part in (MODEL, system, user, repr(float(temperature)), str(seed), str(MAX_TOKENS)):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _api_key() -> str:
    env = os.environ.get("EVAL_GROQ_ENV")
    var = os.environ.get("EVAL_GROQ_VAR", "GROQ_API_KEY")
    if not env:
        raise SystemExit("set EVAL_GROQ_ENV to the .env file holding the Groq key (cache-only replay works without it)")
    key = dotenv_values(env).get(var)
    if not key:
        raise SystemExit(f"{var} not found in EVAL_GROQ_ENV")
    return key


def _pace(est_tokens: int) -> None:
    while True:
        now = time.time()
        while _recent and now - _recent[0][0] > 60:
            _recent.popleft()
        if sum(t for _, t in _recent) + est_tokens <= TPM_BUDGET or not _recent:
            return
        time.sleep(2)


class GroqShim:
    """Replacement for analyzer.llm_call. Set .seed / .tag / .force_temperature before a call."""

    seed = 0
    tag = ""
    force_temperature: float | None = None  # product hardcodes 0.0 for extraction; override for sampling runs
    calls_made = 0

    def __call__(self, system_prompt, user_prompt, model=None, temperature=0.2, api_keys=None):
        if self.force_temperature is not None:
            temperature = self.force_temperature
        k = _key(system_prompt, user_prompt, temperature, self.seed)
        if k in _cache:
            return _cache[k]["response"]
        body = {
            "model": MODEL,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "seed": self.seed,
            "max_tokens": MAX_TOKENS,
            "reasoning_effort": "none",
        }
        est = (len(system_prompt) + len(user_prompt)) // 3 + MAX_TOKENS // 2
        key = _api_key()
        for attempt in range(400):
            _pace(est)
            t = time.time()
            try:
                r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=120)
            except requests.RequestException as e:
                print(f"    [groq] network error ({type(e).__name__}); retry {attempt}", flush=True)
                time.sleep(15)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                txt = r.text[:300]
                if "billing" in txt.lower() or "payment" in txt.lower():
                    raise BillingRequired(txt)
                wait = float(r.headers.get("retry-after", "20") or 20)
                print(f"    [groq] {r.status_code}; retry-after {wait}s; {txt[:160]}", flush=True)
                if os.environ.get("EVAL_STOP_ON_DAILY") and ("(tpd)" in txt.lower() or "(rpd)" in txt.lower()):
                    raise SystemExit(f"daily Groq limit reached: {txt[:200]}")
                time.sleep(wait + 1)  # daily limits are rolling; honour retry-after and continue
                continue
            if r.status_code in (402, 403) or "billing" in r.text[:300].lower():
                raise BillingRequired(r.text[:300])
            r.raise_for_status()
            d = r.json()
            break
        else:
            raise RuntimeError("Groq unavailable after retries")
        usage = d.get("usage", {})
        _recent.append((time.time(), usage.get("total_tokens", est)))
        rec = {
            "key": k, "tag": self.tag, "model": MODEL, "model_reported": d.get("model"),
            "system_fingerprint": d.get("system_fingerprint"),
            "temperature": temperature, "seed": self.seed, "max_tokens": MAX_TOKENS,
            "prompt_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
            "finish_reason": d["choices"][0].get("finish_reason"),
            "wall_s": round(time.time() - t, 2),
            "ratelimit_remaining_requests": r.headers.get("x-ratelimit-remaining-requests"),
            "called_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "response": d["choices"][0]["message"].get("content") or "",
        }
        _cache[k] = rec
        with CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        GroqShim.calls_made += 1
        return rec["response"]


shim = GroqShim()
analyzer.llm_call = shim  # every analyzer.* function now uses the shim


def load_companies() -> list[dict]:
    return json.loads((ROOT / "ground_truth" / "companies.json").read_text(encoding="utf-8"))

"""`score.py` must produce the same numbers whichever provider the environment names.

The truncation flag is the one quantity in the scorer that needs the cached
response rather than the discovery record, and it used to be looked up through
the single active provider's shim. `response_record` returned `{}` for any record
whose model was not that provider's, so:

  * `EVAL_PROVIDER=groq`      -> truncation known for the Groq run, unknown for Haiku
  * `EVAL_PROVIDER=anthropic` -> known for Haiku, unknown for the Groq run

Neither invocation could produce a complete `results/per_run.json`, and the
committed file silently recorded whichever half the person who last ran it had
set. A reader reproducing the numbers got a different file and no warning.

Truncation matters here: a response cut off at `max_tokens` parses to `[]`, which
scores identically to an honest "no competitors found". One Haiku response in the
paid run is truncated, so "unknown" is not a harmless placeholder.

Looking up every provider's cache needs no key and sends nothing -- a cache read
is the opposite of a request -- and takes no ledger lock.
"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import common  # noqa: E402
import score  # noqa: E402
from common import PROVIDERS  # noqa: E402

REPO = HERE.parent
RESULTS = HERE / "results"


def _run_scorer(provider: str) -> list[dict]:
    env = {**os.environ, "PYTHONPATH": str(REPO), "EVAL_PROVIDER": provider}
    out = subprocess.run([sys.executable, str(HERE / "score.py")],
                         capture_output=True, text=True, env=env, cwd=str(REPO))
    assert out.returncode == 0, f"{provider}: {out.stderr[-2000:]}"
    return json.loads((RESULTS / "per_run.json").read_text(encoding="utf-8"))


def _truncation_by_model(rows: list[dict]) -> dict[str, set]:
    by: dict[str, set] = {}
    for r in rows:
        if r["model"] != "none (no LLM)":
            by.setdefault(r["model"], set()).add(r["truncated"])
    return by


def test_the_cache_key_has_one_implementation_shared_with_the_shim():
    """If the scorer recomputed the key itself the two could drift apart silently.

    `replace(..., ledger=None)` matters: constructing a shim on the real paid
    provider acquires the ledger lock and only releases it at interpreter exit, so
    an in-process shim here would hold the lock for the rest of the pytest session
    and every later child process that needs it would fail. The key does not depend
    on the ledger.
    """
    for name in ("groq", "anthropic"):
        p = replace(PROVIDERS[name], ledger=None)
        shim = common.LLMShim(p, client=object())
        shim.seed = 7
        assert common.cache_key(p, "sys", "user", 0.0, seed=7) == shim.key("sys", "user", 0.0)


def test_cached_responses_are_found_for_a_model_that_is_not_the_active_provider():
    """The core defect, at the level of the one function that had it."""
    recs = score.cached_responses()
    for model in ("qwen/qwen3.8-27b", "claude-haiku-4-5-20251001"):
        assert recs.get(model), f"no cached responses loaded for {model}"


def test_every_scored_record_has_a_known_truncation_flag(tmp_path):
    """Run the scorer as a user would, then check nothing is left unknown."""
    backup = tmp_path / "per_run.json"
    shutil.copy(RESULTS / "per_run.json", backup)
    try:
        rows = _run_scorer("groq")
        unknown = [r for r in rows if r["model"] != "none (no LLM)" and r["truncated"] is None]
        assert not unknown, f"{len(unknown)} records with unknown truncation, e.g. {unknown[:2]}"
        assert set(_truncation_by_model(rows)) == {"qwen/qwen3.8-27b", "claude-haiku-4-5-20251001"}
    finally:
        shutil.copy(backup, RESULTS / "per_run.json")


def test_the_scored_output_does_not_depend_on_which_provider_the_environment_names(tmp_path):
    """The decisive test: same bytes under either EVAL_PROVIDER.

    This is what makes the committed `results/` trustworthy -- otherwise the file
    records the env var of whoever ran it last.
    """
    backup = tmp_path / "per_run.json"
    shutil.copy(RESULTS / "per_run.json", backup)
    try:
        as_groq = _run_scorer("groq")
        as_anthropic = _run_scorer("anthropic")
        assert as_groq == as_anthropic
        # And the agreement is on known values, not on both being unknown.
        assert all(r["truncated"] is not None for r in as_groq if r["model"] != "none (no LLM)")
    finally:
        shutil.copy(backup, RESULTS / "per_run.json")


def test_the_paid_run_has_exactly_the_truncated_responses_the_write_up_reports():
    """Guards the number quoted in RESULTS.md against a silent change."""
    rows = json.loads((RESULTS / "per_run.json").read_text(encoding="utf-8"))
    haiku = [r for r in rows if r["model"] == "claude-haiku-4-5-20251001"]
    assert len(haiku) == 192
    truncated = [r for r in haiku if r["truncated"]]
    assert len(truncated) == 1, [(r["cond"], r["id"]) for r in truncated]
    assert truncated[0]["cond"] == "b2_prior_knowledge"

"""The paid Haiku run must replay offline, from a cache committed to the repo.

Why this is a separate file from `test_transport.py`: the provider is chosen from
`EVAL_PROVIDER` at import time, and `test_transport.py` runs under the default
`groq`. Switching it in-process would change `common.shim` under the other tests,
so each case here runs the replay in a child process with the environment it needs.

Why a committed cache at all. The free Groq run's cache has always lived in
`raw/llm_cache.jsonl`, so anyone can re-derive its numbers with no key. The paid
run's working cache lives in the user-level state directory next to the cost
ledger and its lock, deliberately: those three move together, so no repo edit can
hand a run a fresh $0 budget. But that also meant a reader could not reproduce the
paid numbers at all -- the evidence for them sat outside the repository.

So the Anthropic provider reads a committed replay cache in addition to its state
cache, and still writes only to the state cache. Adding a read-only cache source
cannot increase spend: every hit it serves is a request not sent.

The decisive test is `..._with_the_state_directory_unreachable`: it moves the state
directory away, so the committed file is the only thing that can answer, and any
record missing from it becomes an attempted API call, which the child turns into a
failure rather than a charge.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

REPO = HERE.parent
COMMITTED = HERE / "raw" / "llm_cache_haiku.jsonl"
RUN = HERE / "raw" / "discovery_haiku.jsonl"

# Replays every record of the paid run and prints the number of API calls it had to
# make. Run as a child process so EVAL_PROVIDER=anthropic applies at import time.
_REPLAY = r"""
import json, sys
from pathlib import Path
HERE = Path(sys.argv[1])
sys.path.insert(0, str(HERE))
import common, analyzer
import run_discovery as rd

assert common.shim.p.name == "anthropic", common.shim.p.name
common.install_shim()   # the entry point's job; without it the product's real transport runs

def no_network(*a, **k):
    raise AssertionError("replay tried to reach the API")
common.shim._send_anthropic = common.shim._send_groq = no_network

ret = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (HERE / "raw" / "retrieval").glob("*.json")}
recs = [json.loads(x) for x in (HERE / "raw" / "discovery_haiku.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
before = common.shim.calls_made
for r in recs:
    content = rd.content_for(r["cond"], r["id"], ret, r.get("evidence_from"))
    analyzer.COMPETITOR_EXTRACTION_PROMPT = rd.prompt_for(r["cond"])
    common.shim.seed, common.shim.force_temperature = r["seed"], r["temperature"]
    try:
        preds = analyzer.extract_competitors_from_search(r["name"], content, model=common.MODEL)
    finally:
        common.shim.force_temperature = None
    assert preds == r["predictions"], f'{r["cond"]}:{r["id"]}'
print(f"RECORDS={len(recs)} CALLS={common.shim.calls_made - before}")
"""


def _replay(**env_overrides) -> str:
    env = {**os.environ, "PYTHONPATH": str(REPO), "EVAL_PROVIDER": "anthropic"}
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    out = subprocess.run([sys.executable, "-c", _REPLAY, str(HERE)],
                         capture_output=True, text=True, env=env, cwd=str(REPO))
    assert out.returncode == 0, f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    return out.stdout.strip().splitlines()[-1]


def test_the_committed_cache_exists_and_covers_every_record_of_the_paid_run():
    assert COMMITTED.exists(), f"{COMMITTED} is the reader's only copy of the paid responses"
    keys = {json.loads(x)["key"] for x in COMMITTED.read_text(encoding="utf-8").splitlines() if x.strip()}
    n_records = len([x for x in RUN.read_text(encoding="utf-8").splitlines() if x.strip()])
    assert len(keys) == n_records, f"{len(keys)} cached responses for {n_records} records"


def test_the_committed_cache_holds_no_key_shaped_string():
    # It is committed to a public repository, so this is checked, not assumed.
    text = COMMITTED.read_text(encoding="utf-8")
    for marker in ("sk-ant-", "gsk_", "AKIA", "Bearer "):
        assert marker not in text, f"{marker!r} appears in the committed cache"


def test_the_paid_run_replays_with_no_api_calls():
    assert _replay().endswith("CALLS=0")


def test_the_paid_run_replays_with_the_state_directory_unreachable(tmp_path):
    """The committed cache alone is enough: no state cache, no network, no spend.

    USERPROFILE is what moves `STATE_DIR` (`common.py` documents this), so pointing
    it at an empty directory removes the working cache and the ledger from reach.
    Without the committed cache being read, all 192 records would miss and the
    child would die on the first attempted request.
    """
    line = _replay(USERPROFILE=str(tmp_path))
    assert line.endswith("CALLS=0"), line
    assert "RECORDS=192" in line, line
    # Nothing was written back into the relocated state directory either.
    assert not list(tmp_path.rglob("cost_ledger_haiku.jsonl"))


def test_writes_still_go_to_the_state_cache_not_the_committed_one(tmp_path, monkeypatch):
    """The committed cache is read-only for the harness.

    If a run could append to it, a paid response would land in the repository
    working tree as an untracked diff, and the file the tests above trust as the
    record of the run would no longer match the run.
    """
    import common
    from common import PROVIDERS

    p = PROVIDERS["anthropic"]
    assert p.replay_cache == COMMITTED
    assert p.cache == common.STATE_DIR / "llm_cache_haiku.jsonl"
    assert p.replay_cache != p.cache
    # The written-to path is the one under the state directory, which is not in the repo.
    assert REPO not in p.cache.parents


@pytest.mark.parametrize("provider", ["groq"])
def test_the_free_provider_is_untouched_by_the_replay_cache_change(provider):
    """The Groq run's cache was already committed; it gains no second source."""
    from common import PROVIDERS

    assert PROVIDERS[provider].replay_cache is None

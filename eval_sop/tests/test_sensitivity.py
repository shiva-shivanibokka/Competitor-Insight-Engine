"""Offline tests for the sensitivity analysis.

The analysis covers two kinds of quantity, and the distinction is the reason
this file exists:

  * model-dependent -- verbatim-only P@4 and a_full P@4 by coverage stratum,
    which read a model's predictions and therefore need one block per model;
  * model-independent -- retrieval coverage and the thin-scrape support rates,
    which read only the ground truth, the cached search text and
    profile_support.json, and are therefore reported once.

`sensitivity.py` originally read `raw/discovery.jsonl` by name while
`score.py` globbed `raw/discovery*.jsonl`. Once a second model's run existed
(`raw/discovery_haiku.jsonl`) the two disagreed silently: the scorer reported
both models and the sensitivity analysis reported only whichever one happened
to be in the unsuffixed file, with nothing in its output saying so.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sensitivity  # noqa: E402
from common import ROOT  # noqa: E402

RAW = ROOT / "raw"


def _models_on_disk() -> set[str]:
    """Every model that has a committed discovery run, from the runs themselves."""
    found = set()
    for f in sorted(RAW.glob("discovery*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                found.add(json.loads(line)["model"])
    return found


def test_more_than_one_model_has_a_committed_run():
    # Guards the test below: with a single run file it would pass trivially and
    # would not notice the glob regressing to a hardcoded filename.
    assert len(_models_on_disk()) >= 2


def test_the_analysis_covers_every_model_that_has_a_run():
    got = set(json.loads((ROOT / "results" / "sensitivity.json").read_text(encoding="utf-8"))["models"])
    assert got == _models_on_disk()


def test_every_model_block_carries_the_model_dependent_sections():
    models = json.loads((ROOT / "results" / "sensitivity.json").read_text(encoding="utf-8"))["models"]
    for name, block in models.items():
        assert block["verbatim_only_p@4"], f"{name}: no verbatim-only rows"
        assert block["a_full_p@4_by_coverage"], f"{name}: no coverage strata"
        # a_full over all 48 companies is the row every write-up quotes.
        assert block["verbatim_only_p@4"]["a_full/all"]["n"] == 48


def test_model_independent_sections_are_reported_once_not_per_model():
    out = json.loads((ROOT / "results" / "sensitivity.json").read_text(encoding="utf-8"))
    for key in ("gt_in_search_coverage", "gt_in_search_coverage_loose", "thin_scrape"):
        assert key in out, f"{key} should sit at the top level"
    for block in out["models"].values():
        for key in ("gt_in_search_coverage", "thin_scrape"):
            assert key not in block, f"{key} does not depend on the model; do not duplicate it"


def test_runs_for_a_model_are_gathered_across_every_file_not_just_one():
    """The loader must key on each record's own `model`, not on the filename.

    A hardcoded `discovery.jsonl` satisfies every other assertion here as soon
    as one file happens to hold both models, so this checks the loader directly.
    """
    by_model = sensitivity.runs_by_model(RAW)
    assert set(by_model) == _models_on_disk()
    for name, runs in by_model.items():
        assert all(r["model"] == name for r in runs)
    # Nothing is dropped: the blocks partition the records.
    total = sum(len(v) for v in by_model.values())
    assert total == sum(len([x for x in f.read_text(encoding="utf-8").splitlines() if x.strip()])
                        for f in RAW.glob("discovery*.jsonl"))

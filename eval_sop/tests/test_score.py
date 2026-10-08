"""Offline tests for the discovery scorer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import score  # noqa: E402


def test_leak_detector_flags_few_shot_names():
    assert score.mentions(["Adyen", "PayPal"], "Adyen")
    assert score.mentions(["Square (Block)"], "Square")
    assert not score.mentions(["Squarespace"], "Square")
    assert not score.mentions(["Stripe"], "Adyen")


def test_scorer_source_has_no_control_characters():
    src = (Path(__file__).resolve().parents[1] / "score.py").read_text(encoding="utf-8")
    assert not [c for c in src if ord(c) < 32 and c not in "\n\t"]


def test_truncated_responses_are_detected():
    assert score.is_truncated({"stop_reason": "max_tokens"})          # Anthropic
    assert score.is_truncated({"finish_reason": "length"})            # Groq / OpenAI-style
    assert not score.is_truncated({"stop_reason": "end_turn"})
    assert not score.is_truncated({"finish_reason": "stop"})


def test_scored_runs_carry_a_truncation_flag():
    import json

    score.main()
    per = json.loads((Path(__file__).resolve().parents[1] / "results" / "per_run.json").read_text(encoding="utf-8"))
    llm_rows = [r for r in per if r["model"] != "none (no LLM)"]
    assert llm_rows and all("truncated" in r for r in llm_rows)
    summ = json.loads((Path(__file__).resolve().parents[1] / "results" / "summary.json").read_text(encoding="utf-8"))
    assert all("n_truncated" in r for r in summ)

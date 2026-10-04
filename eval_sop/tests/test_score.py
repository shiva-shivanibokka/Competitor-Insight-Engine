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

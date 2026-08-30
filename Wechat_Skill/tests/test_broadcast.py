"""broadcast_message pure-helper tests.

The operation body is a serial async loop that drives a live WeChat window,
so we only unit-test the pure decision logic (normalize_targets, plan_delays)
imported from src.operations._broadcast. An integration smoke test against
the real operation lives with the live WeChat verification notes, not here.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.operations._broadcast import normalize_targets, plan_delays


# --- normalize_targets ---------------------------------------------------

def test_normalize_targets_accepts_single_string():
    assert normalize_targets("老妈") == ["老妈"]


def test_normalize_targets_dedupes_preserving_order():
    assert normalize_targets(["老妈", "文件传输助手", "老妈", ""]) == ["老妈", "文件传输助手"]


def test_normalize_targets_strips_and_drops_empty():
    assert normalize_targets(["  老妈  ", "", "  ", "老爸"]) == ["老妈", "老爸"]


def test_normalize_targets_empty_input():
    assert normalize_targets([]) == []
    assert normalize_targets("") == []


def test_normalize_targets_none_is_empty():
    # A missing 'targets' param arrives as None; must not crash.
    assert normalize_targets(None) == []


# --- plan_delays ---------------------------------------------------------

def test_plan_delays_last_is_zero():
    delays = plan_delays(3, 500, 300)
    assert len(delays) == 3
    assert delays[-1] == 0
    # Every non-last delay is within [500, 800] = interval + 0..jitter.
    assert all(500 <= d <= 800 for d in delays[:-1])


def test_plan_delays_zero_interval_disables_pacing():
    delays = plan_delays(2, 0, 0)
    assert delays == [0, 0]


def test_plan_delays_deterministic_with_seeded_rng():
    rng = random.Random(42)
    a = plan_delays(4, 500, 300, rng=rng)
    rng2 = random.Random(42)
    b = plan_delays(4, 500, 300, rng=rng2)
    assert a == b
    assert a[-1] == 0


def test_plan_delays_single_target_is_zero():
    # One target: no gaps at all.
    assert plan_delays(1, 500, 300) == [0]


def test_plan_delays_empty():
    assert plan_delays(0, 500, 300) == []


def test_plan_delays_clamps_negatives():
    # Negative interval/jitter must not crash or produce negative waits.
    delays = plan_delays(2, -10, -10)
    assert delays == [0, 0]

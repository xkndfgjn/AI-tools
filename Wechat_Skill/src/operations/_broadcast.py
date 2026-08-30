"""Pure helpers for broadcast_message (no I/O, unit-testable).

These split the small but fiddly decision logic out of the async operation
body so it can be tested without a live WeChat window:

- normalize_targets: accept a single name OR a list, dedupe, strip blanks
- plan_delays: per-target post-send wait (last is 0), with anti-abuse jitter
"""
from __future__ import annotations

import random
from typing import List, Optional, Sequence, Union

TargetsParam = Union[str, Sequence[str]]


def normalize_targets(targets: TargetsParam) -> List[str]:
    """Normalize the targets parameter into a clean ordered list.

    Accepts a single name (str) or any sequence of names. Returns unique
    non-empty names, preserving first-seen order. Blanks are dropped.
    None / missing -> [] (so a missing 'targets' param yields an empty
    list the caller can reject with a clean validation error).
    """
    if targets is None:
        return []
    if isinstance(targets, str):
        raw: List[str] = [targets]
    else:
        raw = list(targets)
    seen: set = set()
    out: List[str] = []
    for t in raw:
        name = (t or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def plan_delays(n: int, interval_ms: int, jitter_ms: int,
                rng: Optional[random.Random] = None) -> List[int]:
    """Per-target post-send delays in ms; the last entry is always 0.

    For n targets there are n-1 gaps between sends. We return a list of
    length n where entry i is how long to wait AFTER sending target i
    before opening the next one. The last entry is 0 (nothing follows).

    interval_ms is a flat floor; jitter_ms adds random.randint(0, jitter_ms)
    so the cadence isn't perfectly regular (cheap anti-abuse). Both are
    clamped to >= 0; pass interval_ms=0 to effectively disable pacing.
    """
    if n <= 0:
        return []
    interval_ms = max(0, int(interval_ms))
    jitter_ms = max(0, int(jitter_ms))
    r = rng or random
    delays: List[int] = []
    for i in range(n):
        if i == n - 1:
            delays.append(0)
        else:
            delays.append(interval_ms + r.randint(0, jitter_ms))
    return delays

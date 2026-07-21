"""Shared primitive: a set of "things that changed" that only grows, never drops a
member once it's in (a reset/rescan is the only way membership shrinks).

Real-Time's "Changes Only" panel, Diff Analyzer's Live "ever changed" tracking, and
Analyze Data's Matrix Live mode (AN3) all need this exact semantics -- defined once
here instead of three divergent implementations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChangedSetDelta:
    """How a changed-set consumer should move in response to a new snapshot --
    computed once here so callers don't have to decide "grew vs shrunk" themselves."""

    # True: the set shrunk (baseline reset / reconfig / restart) -- members is the
    # FULL new set to resync to. False: it grew -- members is only the newly-added
    # ones, so a consumer can add just those without disturbing existing state.
    reset: bool
    members: frozenset[str]


def compute_changed_set_delta(previous: frozenset[str], current: frozenset[str]) -> ChangedSetDelta:
    if current >= previous:
        return ChangedSetDelta(reset=False, members=current - previous)
    return ChangedSetDelta(reset=True, members=current)

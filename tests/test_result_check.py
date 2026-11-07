"""The pacing-only result filter, on the words that name a completion without a change verb."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.result_check import states_change  # noqa: E402


@pytest.mark.parametrize("quote", [
    # Junior script Q10 (07/11/2026). Extraction quoted this every time and the filter threw it
    # away, so a complete story drew another probe.
    "it passed nine out of nine live checks, and then I committed it.",
    "It passed every check on staging.",
    "Once it passed all the migrations tests I committed the change.",
])
def test_a_completion_named_by_passing_or_committing_counts(quote):
    assert states_change(quote)


@pytest.mark.parametrize("quote", [
    # The first four are from stored sessions, where each was a step or a rule, not the outcome.
    "It all got built, and it passed the type checks and lint and the build.",
    "So for Mockingbird my rule is nothing gets committed until I've actually used it live.",
    "I would alert if Redis errors passed 1%, or 429 responses exceeded the baseline",
    "Total CI wall time and the flake rate - reruns that passed second time.",
    "I'm committed to writing tests for everything I touch.",
    "A couple of weeks passed before anyone looked at it again.",
    "We were committed to the March date, so there wasn't much room.",
])
def test_passing_and_committing_in_other_senses_do_not(quote):
    assert not states_change(quote)

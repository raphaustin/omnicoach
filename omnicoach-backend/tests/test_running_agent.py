"""Tests that run with no LLM, no key and no network (LLM_PROVIDER=mock)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "mock")

from app.agents.running import RunningAgent  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.library.catalog import get_catalog  # noqa: E402
from app.llm.provider import MockProvider  # noqa: E402
from app.schemas import AthleteContext  # noqa: E402


@pytest.fixture(scope="module")
def catalog():
    s = get_settings()
    try:
        return get_catalog(str(s.library_path))
    except FileNotFoundError:
        pytest.skip("Library not available; set LIBRARY_PATH.")


@pytest.fixture
def ctx():
    return AthleteContext(
        level="intermediate",
        goal="Olympic triathlon",
        weeks_to_event=14,
        phase="base",
        running_days=["Tue", "Thu", "Sat"],
        max_session_minutes=90,
        reference_performance="10 km in 47:30",
        notes="Right knee gets sore after long runs.",
    )


def test_library_loads(catalog):
    assert len(catalog.codes) == 186


def test_shortlist_respects_phase_and_duration(catalog, ctx):
    agent = RunningAgent(catalog, MockProvider())
    entries = agent.shortlist(ctx)
    assert entries, "base phase should yield candidates"
    for e in entries:
        assert e.family in ("RF", "RAe", "RL", "RRe", "RSP")
        if e.duration_min:
            assert e.duration_min <= ctx.max_session_minutes


def test_shortlist_shrinks_the_prompt(catalog, ctx):
    """The catalog line is what makes a free local model viable."""
    agent = RunningAgent(catalog, MockProvider())
    entries = agent.shortlist(ctx)
    prompt = agent.user_prompt(ctx, entries)
    assert len(prompt) / 4 < 3000, "shortlist prompt should stay small"


def test_schema_pins_codes_to_the_catalog(catalog, ctx):
    agent = RunningAgent(catalog, MockProvider())
    entries = agent.shortlist(ctx)
    schema = agent.response_schema([e.code for e in entries], list(ctx.running_days))
    codes = schema["properties"]["sessions"]["items"]["properties"]["workout_code"]["enum"]
    assert set(codes) <= set(catalog.codes)
    assert schema["properties"]["sessions"]["minItems"] == 3


def test_propose_end_to_end_with_mock(catalog, ctx):
    agent = RunningAgent(catalog, MockProvider())
    proposal, considered, warnings = agent.propose(ctx)
    assert len(proposal.sessions) == 3
    assert considered > 0
    assert warnings == []
    for s in proposal.sessions:
        assert s.workout_code in catalog.codes


def test_taper_phase_selects_taper_families(catalog):
    agent = RunningAgent(catalog, MockProvider())
    ctx = AthleteContext(
        goal="Marathon", weeks_to_event=1, phase="taper", running_days=["Wed"]
    )
    entries = agent.shortlist(ctx)
    assert {e.family for e in entries} <= {"RTa", "RRe", "RF", "RSI"}


def test_unreachable_constraints_raise(catalog):
    """No specific-phase workout fits in 20 minutes — fail loudly, don't guess."""
    agent = RunningAgent(catalog, MockProvider())
    ctx = AthleteContext(
        goal="Marathon",
        weeks_to_event=8,
        phase="specific",
        running_days=["Mon"],
        max_session_minutes=20,
    )
    with pytest.raises(ValueError):
        agent.propose(ctx)


def test_long_runs_do_not_sneak_past_a_duration_budget(catalog):
    """Regression: the 28 distance-based workouts carry duration_sec = 0, so the
    underlying reader lets them satisfy any max_duration_min filter. A 20-minute
    slot must never be offered a 32 km long run."""
    sneaky = catalog.search(max_duration_min=20)
    assert all(e.duration_min for e in sneaky), (
        "unknown-duration workouts must be excluded from duration-filtered searches"
    )

    agent = RunningAgent(catalog, MockProvider())
    ctx = AthleteContext(
        goal="Marathon",
        weeks_to_event=8,
        phase="base",  # base includes RL, the long-run family
        running_days=["Mon"],
        max_session_minutes=20,
        easy_pace_min_per_km=6.0,
    )
    for e in agent.shortlist(ctx):
        assert e.family not in {"RL", "RLFF", "RLMS", "RLSP"}
        assert e.duration_min and e.duration_min <= 20


def test_long_runs_are_offered_when_the_budget_allows(catalog):
    """The fix must not throw the long run out with the bathwater."""
    agent = RunningAgent(catalog, MockProvider())
    ctx = AthleteContext(
        goal="Marathon",
        weeks_to_event=12,
        phase="base",
        running_days=["Sun"],
        max_session_minutes=120,
        easy_pace_min_per_km=6.0,  # -> 20 km budget
    )
    entries = agent.shortlist(ctx)
    longs = [e for e in entries if e.family == "RL"]
    assert longs, "a 2-hour easy budget should offer long runs"
    assert all(e.distance_km <= 20.0 for e in longs)

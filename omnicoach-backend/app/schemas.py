"""The API contract.

These models are the frozen shape of what the front-end sends and receives,
independent of which LLM sits behind them.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Day = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
Phase = Literal["reconditioning", "base", "build", "specific", "taper"]
Level = Literal["beginner", "intermediate", "advanced"]


class PaceZoneResponse(BaseModel):
    """Training pace zone calculated from reference performance."""

    name: str
    min_per_km: float
    description: str

    def format(self) -> str:
        """Format as MM:SS per km."""
        minutes = int(self.min_per_km)
        seconds = int((self.min_per_km - minutes) * 60)
        return f"{minutes}:{seconds:02d}"


class AthleteContext(BaseModel):
    """The diagnosis the agent plans from (top-down method, step 1)."""

    level: Level = "intermediate"
    goal: str = Field(..., examples=["Olympic triathlon"])
    weeks_to_event: int = Field(..., ge=1, le=104)
    phase: Phase = "base"
    running_days: list[Day] = Field(..., min_length=1)
    max_session_minutes: int = Field(90, ge=20, le=300)
    easy_pace_min_per_km: float = Field(
        6.0,
        ge=3.0,
        le=12.0,
        description=(
            "Used to convert the session time budget into a distance budget for "
            "the long-run families, which the library prescribes in kilometres."
        ),
    )
    reference_performance: str | None = Field(None, examples=["10 km in 47:30"])
    pace_zones: dict[str, PaceZoneResponse] | None = Field(
        None,
        description="Training pace zones calculated from reference performance. "
        "Keys: recovery, easy, tempo, threshold_5k, vo2_max, rep",
    )
    notes: str | None = Field(
        None, examples=["Right knee gets sore after long runs."]
    )


class ProposedSession(BaseModel):
    """One session the agent selected — never invented."""

    day: Day
    workout_code: str
    rationale: str


class RunningProposal(BaseModel):
    sessions: list[ProposedSession]


class ProposalResponse(BaseModel):
    proposal: RunningProposal
    candidates_considered: int
    provider: str
    model: str
    warnings: list[str] = []
    # day -> DetailedSession (dict form). Kept loosely typed so the expander can
    # evolve without breaking the contract during the prototype phase.
    detailed_sessions: dict = {}


# ── User-authored sessions (save / create) ──────────────────────────────────

Role = Literal["warmup", "work", "recovery", "cooldown", "rest"]
Zone = Literal["Z1", "Z2", "Z3", "Z4", "Z5", "REST"]


class SessionDraftStep(BaseModel):
    """One atomic step of a session the user is saving or building.

    Give exactly one of duration_sec / distance_m (rest steps use duration_sec).
    """

    role: Role = "work"
    zone: Zone | None = None
    duration_sec: int | None = Field(None, ge=1, le=36000)
    distance_m: int | None = Field(None, ge=1, le=100000)


class SessionDraft(BaseModel):
    """A compact, athlete-agnostic session to persist in the library.

    `name` is the human title; `code` is optional (auto CUS<n> when omitted).
    """

    name: str = Field(..., min_length=1, max_length=120)
    method_family: str = "custom"
    code: str | None = Field(
        None, description="Explicit code; auto-assigned as CUS<n> when omitted"
    )
    steps: list[SessionDraftStep] = Field(..., min_length=1)
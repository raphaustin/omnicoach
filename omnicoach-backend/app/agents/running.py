"""The running expert agent.

Design decision — the agent is a SELECTOR, not a GENERATOR.

The supervisor's library ships 186 canonical sessions that are already
validated, traceable and physiologically coherent. So the agent never invents a
session: it picks a code from a shortlist and says why. Three consequences:

  1. Hallucinated physiology is impossible: the sessions are pre-existing.
  2. Output is verifiable: a code either exists or it does not.
  3. The prompt stays small (~25 tokens per candidate instead of ~8k of JSON),
     so a free local model handles it comfortably.

The shortlist is built by deterministic Python (`Catalog.search`), not by the
LLM. The model only does what a model is good at: judgement over a small set.
"""
from __future__ import annotations

from app.library.catalog import Catalog, CatalogEntry
from app.llm.provider import LLMProvider
from app.schemas import AthleteContext, RunningProposal

SYSTEM = """You are a running coach working inside a multisport training system.

You do NOT invent workouts. You select them from the catalog you are given.

Rules:
- Choose exactly one workout per available day, in the order the days are listed.
- Only use workout codes present in the catalog.
- Respect the athlete's phase: base = mostly easy aerobic volume; build = add
  tempo and cruise intervals; specific = race-pace work; taper = short, sharp,
  low volume; reconditioning = easy only.
- Never place two hard sessions on consecutive days.
- Keep one clearly long session per week when the athlete has 3+ running days.
- Take the athlete's notes seriously: an injury or constraint outranks the plan.
- The rationale must be one short sentence a coach would actually say.
"""

# The long-run families are prescribed by DISTANCE, not duration: they carry no
# known duration, so they cannot be filtered by session length directly.
DISTANCE_FAMILIES = {"RL", "RLFF", "RLMS", "RLSP"}

# Which method families make sense per phase. Deterministic domain knowledge —
# not something we pay an LLM to re-derive on every call.
PHASE_FAMILIES: dict[str, list[str]] = {
    "reconditioning": ["RRe", "RF", "RAe"],
    "base": ["RF", "RAe", "RL", "RRe", "RSP"],
    "build": ["RT", "RCI", "RL", "RF", "RFF", "RSP", "RHR"],
    "specific": ["RT", "RLMS", "RLI", "RSI", "RL", "RAn", "RLFF"],
    "taper": ["RTa", "RRe", "RF", "RSI"],
}


class RunningAgent:
    def __init__(self, catalog: Catalog, provider: LLMProvider):
        self.catalog = catalog
        self.provider = provider

    # -- shortlist (pure Python, no LLM) ------------------------------------
    def shortlist(self, ctx: AthleteContext) -> list[CatalogEntry]:
        """Candidates for this phase that fit inside the session budget.

        Two filters, because the library speaks two languages: most workouts are
        prescribed in minutes, the long runs in kilometres. Converting the time
        budget into a distance budget needs a pace, so we use the athlete's
        declared easy pace — an explicit, conservative assumption rather than a
        hidden one.
        """
        families = PHASE_FAMILIES.get(ctx.phase, [])
        max_km = ctx.max_session_minutes / ctx.easy_pace_min_per_km
        entries: list[CatalogEntry] = []
        seen: set[str] = set()
        for fam in families:
            found = (
                self.catalog.search(family=fam, max_distance_km=max_km)
                if fam in DISTANCE_FAMILIES
                else self.catalog.search(
                    family=fam, max_duration_min=ctx.max_session_minutes
                )
            )
            for e in found:
                if e.code not in seen:
                    seen.add(e.code)
                    entries.append(e)
        entries.sort(key=lambda e: (e.family, e.duration_min or 999))
        return entries

    # -- schema (this is where correctness is enforced) ---------------------
    @staticmethod
    def response_schema(codes: list[str], days: list[str]) -> dict:
        return {
            "type": "object",
            "properties": {
                "sessions": {
                    "type": "array",
                    "minItems": len(days),
                    "maxItems": len(days),
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string", "enum": days},
                            # The hard guarantee: the model physically cannot
                            # emit a code that is not in the catalog.
                            "workout_code": {"type": "string", "enum": codes},
                            "rationale": {"type": "string"},
                        },
                        "required": ["day", "workout_code", "rationale"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["sessions"],
            "additionalProperties": False,
        }

    # -- prompt -------------------------------------------------------------
    @staticmethod
    def user_prompt(ctx: AthleteContext, entries: list[CatalogEntry]) -> str:
        catalog = "\n".join(e.to_line() for e in entries)
        notes = f"\nNotes from the athlete: {ctx.notes}" if ctx.notes else ""
        ref = (
            f"\nReference performance: {ctx.reference_performance}"
            if ctx.reference_performance
            else ""
        )
        return f"""Athlete
- Level: {ctx.level}
- Goal: {ctx.goal}
- Weeks until the event: {ctx.weeks_to_event}
- Current phase: {ctx.phase}
- Running days available: {", ".join(ctx.running_days)}
- Maximum session length: {ctx.max_session_minutes} min{ref}{notes}

Catalog (code | family | length | zones):
{catalog}

Select one workout for each of these days, in this order: {", ".join(ctx.running_days)}.
"""

    # -- run ----------------------------------------------------------------
    def propose(self, ctx: AthleteContext) -> tuple[RunningProposal, int, list[str]]:
        entries = self.shortlist(ctx)
        if not entries:
            raise ValueError(
                f"No workout in the library matches phase '{ctx.phase}' under "
                f"{ctx.max_session_minutes} min."
            )
        codes = [e.code for e in entries]
        days = list(ctx.running_days)

        raw = self.provider.complete_json(
            system=SYSTEM,
            user=self.user_prompt(ctx, entries),
            schema=self.response_schema(codes, days),
        )
        proposal = RunningProposal.model_validate(raw)

        # Belt and braces: the schema should make this impossible, but a hosted
        # provider that ignores `strict` would slip through. Never trust,
        # always verify.
        warnings: list[str] = []
        valid = set(codes)
        for s in proposal.sessions:
            if s.workout_code not in valid:
                warnings.append(
                    f"{s.workout_code} is not in the shortlist — schema not honoured."
                )
        chosen_days = [s.day for s in proposal.sessions]
        if chosen_days != days:
            warnings.append(
                f"Days returned {chosen_days} do not match requested {days}."
            )
        return proposal, len(entries), warnings

    # -- manual swap: alternatives for a single day -------------------------
    def alternatives(self, ctx: AthleteContext, exclude: str | None = None) -> list[CatalogEntry]:
        """The shortlist for one day, minus the current code — for a manual swap."""
        entries = self.shortlist(ctx)
        if exclude:
            entries = [e for e in entries if e.code != exclude]
        return entries

    # -- agent regen of a single day ---------------------------------------
    def propose_one(self, ctx: AthleteContext, day: str, avoid: str | None = None):
        """Regenerate exactly one session for one day.

        Reuses the same shortlist + schema-constrained selection as a full week,
        but for a single day. `avoid` lets the coach ask for 'something else'.
        """
        entries = self.shortlist(ctx)
        if avoid:
            entries = [e for e in entries if e.code != avoid] or entries
        if not entries:
            raise ValueError(
                f"No workout matches phase '{ctx.phase}' under {ctx.max_session_minutes} min."
            )
        codes = [e.code for e in entries]
        raw = self.provider.complete_json(
            system=SYSTEM,
            user=self.user_prompt(ctx, entries) + f"\n\nSelect ONE workout for {day} only.",
            schema=self.response_schema(codes, [day]),
        )
        from app.schemas import RunningProposal
        proposal = RunningProposal.model_validate(raw)
        sess = proposal.sessions[0]
        warnings = []
        if sess.workout_code not in set(codes):
            warnings.append(f"{sess.workout_code} not in shortlist.")
        return sess, len(entries), warnings

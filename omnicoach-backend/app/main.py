"""OmniCoach back-end — vertical slice.

One agent, one real LLM call, end to end. Everything else (coach validation,
accounts, the other two sports) comes after this works.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.running import RunningAgent
from app.training.session_expander import SessionExpander, paces_for
from app.config import get_settings
from app.library.catalog import get_catalog
from app.llm.provider import LLMError, get_provider
from app.schemas import (
    AthleteContext,
    PaceZoneResponse,
    ProposalResponse,
    SessionDraft,
)
from app.library.session_writer import SessionWriteError, save_session
from pydantic import BaseModel
from app.training.pace_calculator import PaceCalculator

app = FastAPI(
    title="OmniCoach API",
    version="0.1.0",
    description="Multi-agent multisport training planner — vertical slice.",
)

# The front-end prototype is a local file; keep CORS permissive in dev only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Report what will actually answer, not what is configured."""
    try:
        p = get_provider(get_settings())
        return {"status": "ok", "provider": p.name, "model": p.model}
    except LLMError as e:
        return {"status": "degraded", "detail": str(e)}


@app.get("/library/stats")
def library_stats():
    s = get_settings()
    try:
        return get_catalog(str(s.library_path)).stats()
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.get("/athlete/pace-zones")
def get_pace_zones(reference_performance: str):
    """Calculate training pace zones from a reference performance.

    Example: GET /athlete/pace-zones?reference_performance=10%20km%20in%2047:30

    Returns:
    {
      "recovery": {"name": "Recovery", "min_per_km": 0.98, "description": "..."},
      "easy": {"name": "Easy", "min_per_km": 0.90, "description": "..."},
      ...
    }
    """
    zones_raw = PaceCalculator.from_reference(reference_performance)
    if not zones_raw:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse reference performance: {reference_performance}",
        )

    # Convert to API response model
    return {
        name: PaceZoneResponse(
            name=zone.name,
            min_per_km=zone.min_per_km,
            description=zone.description,
        )
        for name, zone in zones_raw.items()
    }


@app.post("/agents/running/propose", response_model=ProposalResponse)
def propose_running(ctx: AthleteContext):
    """Ask the running agent for one week of sessions."""
    s = get_settings()
    try:
        catalog = get_catalog(str(s.library_path))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    # Calculate pace zones from reference performance if available
    if ctx.reference_performance:
        zones_raw = PaceCalculator.from_reference(ctx.reference_performance)
        if zones_raw:
            # Convert to API response model
            ctx.pace_zones = {
                name: PaceZoneResponse(
                    name=zone.name,
                    min_per_km=zone.min_per_km,
                    description=zone.description,
                )
                for name, zone in zones_raw.items()
            }
            # Update easy_pace_min_per_km with calculated value
            if "easy" in ctx.pace_zones:
                ctx.easy_pace_min_per_km = ctx.pace_zones["easy"].min_per_km

    try:
        provider = get_provider(s)
        agent = RunningAgent(catalog, provider)
        proposal, considered, warnings = agent.propose(ctx)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Expand each selected code into detailed, athlete-specific steps.
    expander = SessionExpander(catalog.reader)
    paces = paces_for(ctx.reference_performance)
    detailed = {}
    for sess in proposal.sessions:
        try:
            detailed[sess.day] = expander.expand(sess.workout_code, paces).__dict__
        except Exception as exc:  # never let one bad code break the whole week
            warnings.append(f"Could not expand {sess.workout_code}: {exc}")

    return ProposalResponse(
        proposal=proposal,
        candidates_considered=considered,
        provider=provider.name,
        model=provider.model,
        warnings=warnings,
        detailed_sessions=detailed,
    )


# ── Editing a single session ────────────────────────────────────────────────

class EditContext(BaseModel):
    context: AthleteContext
    day: str
    current_code: str | None = None
    all_sessions: bool = False  # True = browse the whole library, ignore phase/budget


@app.post("/agents/running/alternatives")
def running_alternatives(req: EditContext):
    """List swap candidates for one day.

    Default: the phase-appropriate shortlist that fits the athlete's budget.
    With `all_sessions=true`: the whole library (every family, any length), so
    the coach can override the automatic filtering. No UI cap either way.
    """
    s = get_settings()
    try:
        catalog = get_catalog(str(s.library_path))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if req.all_sessions:
        entries = [e for e in catalog.all_entries() if e.code != req.current_code]
    else:
        provider = get_provider(s)
        agent = RunningAgent(catalog, provider)
        entries = agent.alternatives(req.context, exclude=req.current_code)
    expander = SessionExpander(catalog.reader)
    paces = paces_for(req.context.reference_performance)
    return {
        "day": req.day,
        "all": req.all_sessions,
        "total": len(entries),
        "alternatives": [
            {
                "code": e.code,
                "family": e.family,
                "detail": expander.expand(e.code, paces).__dict__,
            }
            for e in entries
        ],
    }

@app.post("/agents/running/regenerate-session")
def regenerate_session(req: EditContext):
    """Ask the agent to propose a fresh session for one day."""
    s = get_settings()
    try:
        catalog = get_catalog(str(s.library_path))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    try:
        provider = get_provider(s)
        agent = RunningAgent(catalog, provider)
        sess, considered, warnings = agent.propose_one(
            req.context, req.day, avoid=req.current_code
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    expander = SessionExpander(catalog.reader)
    paces = paces_for(req.context.reference_performance)
    return {
        "day": req.day,
        "session": {"day": sess.day, "workout_code": sess.workout_code, "rationale": sess.rationale},
        "detail": expander.expand(sess.workout_code, paces).__dict__,
        "candidates_considered": considered,
        "provider": provider.name,
        "model": provider.model,
        "warnings": warnings,
    }


# ── Saving / creating library sessions ──────────────────────────────────────

@app.post("/library/sessions", status_code=201)
def create_library_session(draft: SessionDraft):
    """Persist a user-authored session (saved from a plan, or built from scratch).

    The session is athlete-agnostic (zones + durations, no personal paces). It
    is written to the library, the index is rebuilt, and the catalog cache is
    cleared so the new code is immediately selectable and expandable.
    """
    s = get_settings()
    try:
        code = save_session(
            human_name=draft.name,
            method_family=draft.method_family,
            steps=[step.model_dump() for step in draft.steps],
            library_dir=s.library_path,
            code=draft.code,
        )
    except SessionWriteError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e

    # Make the new session visible to every subsequent request.
    get_catalog.cache_clear()
    catalog = get_catalog(str(s.library_path))

    # Return it expanded (no paces: it is stored athlete-agnostic).
    detailed = SessionExpander(catalog.reader).expand(code, None).__dict__
    return {"code": code, "total_sessions": len(catalog.codes), "detailed": detailed}


@app.get("/library/custom-codes")
def list_custom_codes():
    """List the codes of user-authored sessions (family CUS)."""
    s = get_settings()
    try:
        catalog = get_catalog(str(s.library_path))
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    codes = [c for c in catalog.codes if c.upper().startswith("CUS")]
    return {"codes": codes}
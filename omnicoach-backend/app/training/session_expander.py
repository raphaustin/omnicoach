"""Turn a selected workout code into a detailed, athlete-specific session.

The running agent picks a code (e.g. RLFF4). That code, on its own, is just a
label. This module expands it into what an athlete actually needs to see:

  * every step (warm-up, work, recovery, cool-down),
  * how long or how far each step is,
  * and the **target pace for that step, computed for this athlete**.

The pace comes from mapping the library's provider-native zones (Z1..Z5) onto
the athlete's personal pace zones (from the VDOT calculator). That mapping is the
piece the supervisor's library explicitly said must live in a separate layer —
this is that layer.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from app.library.workout_library_reader import (
    WorkoutLibrary,
    iter_atomic_steps,
    step_zone,
)
from app.training.pace_calculator import PaceCalculator, PaceZone


# ── Zone mapping ────────────────────────────────────────────────────────────
# 80/20 provider zones -> the athlete's computed pace zones.
# Z1/Z2 are easy aerobic; Z3 tempo/threshold; Z4 5k-ish; Z5 VO2/rep.
# This is a deliberate, documented mapping — not a silent equivalence.
ZONE_TO_PACE_KEY = {
    "Z1": "recovery",
    "Z2": "marathon",
    "Z3": "tempo",
    "Z4": "threshold_5k",
    "Z5": "vo2_max",
}

ZONE_LABEL = {
    "Z1": "Easy / recovery",
    "Z2": "Aerobic endurance",
    "Z3": "Tempo / threshold",
    "Z4": "5K intensity",
    "Z5": "VO2max / reps",
}

ROLE_LABEL = {
    "warmup": "Warm-up",
    "work": "Work",
    "recovery": "Recovery",
    "cooldown": "Cool-down",
    "rest": "Rest",
}


@dataclass
class DetailedStep:
    order: int
    role: str            # warmup | work | recovery | cooldown | rest
    role_label: str
    zone: str | None     # Z1..Z5
    zone_label: str | None
    duration_sec: int | None
    distance_m: int | None
    target_pace_min_per_km: float | None
    target_pace_label: str | None   # "4:30"
    est_distance_m: int | None      # filled in when the step is time-based
    est_duration_sec: int | None    # filled in when the step is distance-based


@dataclass
class DetailedSession:
    code: str
    family: str
    total_duration_sec: int | None
    total_distance_m: int | None
    est_total_distance_m: int | None
    est_total_duration_sec: int | None
    steps: list[dict]
    zone_distribution: dict[str, int]  # zone -> seconds (estimated where needed)


def _fmt_pace(pace_min_per_km: float) -> str:
    m = int(pace_min_per_km)
    s = int(round((pace_min_per_km - m) * 60))
    if s == 60:
        m, s = m + 1, 0
    return f"{m}:{s:02d}"


class SessionExpander:
    def __init__(self, library: WorkoutLibrary):
        self.library = library

    def expand(
        self, code: str, paces: dict[str, PaceZone] | None
    ) -> DetailedSession:
        w = self.library.get(code)
        pres = w.document["prescription"]
        steps: list[DetailedStep] = []

        est_total_dist = 0
        est_total_dur = 0
        zone_seconds: dict[str, int] = {}

        for i, (raw, _ctx) in enumerate(iter_atomic_steps(pres["steps"])):
            zone = step_zone(raw)
            role = raw.get("role") or "work"
            dur = raw.get("duration") or {}
            dur_sec = dur.get("value_sec")
            dist_m = dur.get("value_m")

            pace = None
            pace_label = None
            if zone and paces:
                key = ZONE_TO_PACE_KEY.get(zone)
                if key and key in paces:
                    pace = round(paces[key].min_per_km, 2)
                    pace_label = _fmt_pace(pace)

            # Fill in the missing dimension using the target pace, so the athlete
            # always sees both a distance and a duration.
            est_dist = None
            est_dur = None
            if pace:
                if dur_sec and not dist_m:
                    est_dist = int(round((dur_sec / 60) / pace * 1000))
                elif dist_m and not dur_sec:
                    est_dur = int(round((dist_m / 1000) * pace * 60))

            eff_sec = dur_sec or est_dur or 0
            if zone:
                zone_seconds[zone] = zone_seconds.get(zone, 0) + int(eff_sec)
            est_total_dur += int(eff_sec)
            est_total_dist += int(dist_m or est_dist or 0)

            steps.append(
                DetailedStep(
                    order=i,
                    role=role,
                    role_label=ROLE_LABEL.get(role, role.title()),
                    zone=zone,
                    zone_label=ZONE_LABEL.get(zone) if zone else None,
                    duration_sec=int(dur_sec) if dur_sec else None,
                    distance_m=int(dist_m) if dist_m else None,
                    target_pace_min_per_km=pace,
                    target_pace_label=pace_label,
                    est_distance_m=est_dist,
                    est_duration_sec=est_dur,
                )
            )

        known_dur = pres.get("known_duration_sec") or 0
        known_dist = pres.get("known_distance_m") or 0
        return DetailedSession(
            code=code,
            family=w.family,
            total_duration_sec=int(known_dur) or None,
            total_distance_m=int(known_dist) or None,
            est_total_distance_m=est_total_dist or None,
            est_total_duration_sec=est_total_dur or None,
            steps=[asdict(s) for s in steps],
            zone_distribution=zone_seconds,
        )


def paces_for(reference_performance: str | None) -> dict[str, PaceZone] | None:
    if not reference_performance:
        return None
    return PaceCalculator.from_reference(reference_performance)

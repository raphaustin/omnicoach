"""Create and persist user-authored workout sessions.

The canonical library JSON (the 1000-line, FIT-derived documents) is generated
by the supervisor's `fit_to_canonical.py`. We never fabricate that. Instead we
build the **minimal valid** document that the reader and the expander actually
consume:

  * the 9 required top-level keys (see `validate_minimal`);
  * a `prescription.steps` list of atomic steps, each carrying a role, a
    provider zone (Z1..Z5) and a time- or distance-based duration.

A saved session is **athlete-agnostic**: it stores zones and durations, never
personal paces. Paces are recomputed per athlete by `session_expander` at
display time — exactly like the supervisor's library.

Storage note: sessions are written into the same `converted/` directory and
registered in its `index.json` via `rebuild_index`. They persist on disk
(surviving restarts) but are machine-local — real cross-account persistence is
the later SQLite step.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from app.library.workout_library_reader import (
    canonical_code,
    rebuild_index,
    validate_minimal,
)

# Which zone maps to which intensity label / number. REST has no provider zone.
_ZONE_NUMBER = {"Z1": 1, "Z2": 2, "Z3": 3, "Z4": 4, "Z5": 5}
_ROLE_INTENSITY = {
    "warmup": "warmup",
    "work": "active",
    "recovery": "recovery",
    "cooldown": "cooldown",
    "rest": "rest",
}
_VALID_ROLES = set(_ROLE_INTENSITY)


class SessionWriteError(Exception):
    """A save failed for a reason the caller should surface as HTTP.

    `status` is the HTTP status code the API layer should use.
    """

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


# ── Building the canonical document ─────────────────────────────────────────

def _build_step(index: int, raw: dict[str, Any]) -> dict[str, Any]:
    role = (raw.get("role") or "work").lower()
    if role not in _VALID_ROLES:
        raise SessionWriteError(
            f"step {index}: role must be one of {sorted(_VALID_ROLES)}, got {role!r}"
        )

    zone = raw.get("zone")
    zone = zone.upper() if isinstance(zone, str) else None
    dur_sec = raw.get("duration_sec")
    dist_m = raw.get("distance_m")

    if dur_sec and dist_m:
        raise SessionWriteError(
            f"step {index}: give either duration_sec or distance_m, not both"
        )
    if not dur_sec and not dist_m:
        raise SessionWriteError(
            f"step {index}: a step needs a duration_sec or a distance_m"
        )

    if dur_sec:
        duration = {"type": "time", "value_sec": float(dur_sec)}
    else:
        duration = {"type": "distance", "value_m": float(dist_m)}

    # Target: a provider zone for Z1..Z5, an explicit rest otherwise.
    if zone in _ZONE_NUMBER:
        number = _ZONE_NUMBER[zone]
        target = {
            "type": "provider_zone",
            "provider": "user",
            "system": "user_zones",
            "zone_code": zone,
            "zone_number": number,
            "label": f"Zone {number}",
        }
        notes = f"Zone {number}"
    else:
        target = {"type": "rest"}
        notes = "Rest"

    return {
        "source_index": index,
        "kind": "step",
        "role": role,
        "intensity": _ROLE_INTENSITY[role],
        "notes": notes,
        "duration": duration,
        "target": target,
    }


def build_canonical(
    *,
    code: str,
    human_name: str,
    method_family: str,
    steps: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a minimal canonical document that passes `validate_minimal`."""
    if not steps:
        raise SessionWriteError("a session needs at least one step")

    built_steps: list[dict[str, Any]] = []
    total_sec = 0.0
    total_m = 0.0
    for i, raw in enumerate(steps):
        step = _build_step(i, raw)
        dur = step["duration"]
        if dur["type"] == "time":
            total_sec += dur["value_sec"]
        else:
            total_m += dur["value_m"]
        built_steps.append(step)

    workout_key = f"custom_{code.lower()}_{_short_hash(code, human_name, built_steps)}"

    document: dict[str, Any] = {
        "schema_version": "1.2.0",
        "workout_key": workout_key,
        "name": code,                       # the reader derives the code from this
        "description": human_name.strip() or code,
        "sport": "running",
        "classification": {
            "method_family": method_family or "custom",
            "workout_type": "structured_workout",
            "primary_objective": None,
            "classification_status": "user_created",
        },
        "prescription": {
            "steps": built_steps,
            "known_duration_sec": total_sec,
            "known_distance_m": total_m,
        },
        "applicability": {
            "appropriate_phases": [],
            "minimum_level": None,
            "maximum_level": None,
            "coach_review_required": True,
        },
        "source": {
            "provider": "user-created",
            "license": "user-owned",
            "authorization_note": "Created by the user in-app",
            "original_format": None,
        },
        "validation": {
            "structure_valid": True,
            "semantic_review_required": False,
            "warning_count": 0,
            "warnings": [],
        },
        "intensity_model": {
            "type": "user_defined_zone_system",
            "provider": "user",
            "system_id": "user_zones",
            "sport": "running",
            "available_zone_codes": ["Z1", "Z2", "Z3", "Z4", "Z5", "REST"],
        },
    }

    errors = validate_minimal(document)
    if errors:  # should never happen, but never write an invalid document
        raise SessionWriteError("built an invalid document: " + "; ".join(errors))
    return document


def _short_hash(code: str, human_name: str, steps: list[dict[str, Any]]) -> str:
    raw = repr((code, human_name, steps)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:10]


# ── Persisting ──────────────────────────────────────────────────────────────

def _converted_dir(library_dir: str | Path) -> Path:
    root = Path(library_dir)
    if root.name != "converted" and (root / "converted").is_dir():
        root = root / "converted"
    return root


def _existing_codes(root: Path) -> set[str]:
    codes: set[str] = set()
    for path in root.glob("*.json"):
        if path.name == "index.json":
            continue
        codes.add(canonical_code(path.stem, path.name).upper())
    return codes


def _next_custom_code(root: Path) -> str:
    highest = 0
    for path in root.glob("*.json"):
        m = re.fullmatch(r"cus(\d+)", path.stem.lower())
        if m:
            highest = max(highest, int(m.group(1)))
    return f"CUS{highest + 1}"


def save_session(
    *,
    human_name: str,
    method_family: str,
    steps: list[dict[str, Any]],
    library_dir: str | Path,
    code: str | None = None,
) -> str:
    """Write a user session to the library and register it. Returns its code."""
    root = _converted_dir(library_dir)
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)

    existing = _existing_codes(root)

    if code:
        code = code.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]*", code):
            raise SessionWriteError(
                "code must start with a letter and contain only letters/digits"
            )
        if code in existing:
            raise SessionWriteError(f"code {code} already exists", status=409)
    else:
        code = _next_custom_code(root)

    document = build_canonical(
        code=code,
        human_name=human_name,
        method_family=method_family,
        steps=steps,
    )

    import json

    (root / f"{code.lower()}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # rebuild_index re-validates every file and refuses duplicates for us.
    rebuild_index(root)
    return code

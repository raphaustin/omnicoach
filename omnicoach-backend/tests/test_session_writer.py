"""User-authored sessions: build a valid doc, persist it, read it back, expand it.

These tests use a throwaway temp directory and need no licensed library data.
"""
from __future__ import annotations

import pytest

from app.library.session_writer import (
    SessionWriteError,
    build_canonical,
    save_session,
)
from app.library.workout_library_reader import WorkoutLibrary, validate_minimal
from app.training.session_expander import SessionExpander


def _draft_steps():
    return [
        {"role": "warmup", "zone": "Z1", "duration_sec": 600},
        {"role": "work", "zone": "Z4", "duration_sec": 300},
        {"role": "recovery", "zone": "Z1", "duration_sec": 120},
        {"role": "cooldown", "zone": "Z1", "duration_sec": 300},
    ]


def test_built_document_is_valid():
    doc = build_canonical(
        code="CUS1", human_name="My tempo", method_family="custom", steps=_draft_steps()
    )
    assert validate_minimal(doc) == []
    assert doc["name"] == "CUS1"
    assert doc["description"] == "My tempo"
    assert doc["prescription"]["known_duration_sec"] == 1320.0


def test_save_then_reader_and_expander(tmp_path):
    code = save_session(
        human_name="My tempo",
        method_family="custom",
        steps=_draft_steps(),
        library_dir=tmp_path,
    )
    assert code == "CUS1"

    # The reader loads it (index was rebuilt for us).
    lib = WorkoutLibrary.from_directory(tmp_path)
    assert code in lib.list_codes()
    rec = lib.get(code)
    assert rec.family == "CUS"
    assert rec.zones == {"Z1", "Z4"}

    # The expander turns it into detailed steps (no paces -> None targets ok).
    detailed = SessionExpander(lib).expand(code, None)
    assert detailed.code == "CUS1"
    assert len(detailed.steps) == 4
    assert detailed.total_duration_sec == 1320


def test_auto_increment_code(tmp_path):
    first = save_session(
        human_name="a", method_family="custom", steps=_draft_steps(), library_dir=tmp_path
    )
    second = save_session(
        human_name="b", method_family="custom", steps=_draft_steps(), library_dir=tmp_path
    )
    assert (first, second) == ("CUS1", "CUS2")


def test_duplicate_explicit_code_is_rejected(tmp_path):
    save_session(
        human_name="a",
        method_family="custom",
        steps=_draft_steps(),
        library_dir=tmp_path,
        code="MINE1",
    )
    with pytest.raises(SessionWriteError) as exc:
        save_session(
            human_name="b",
            method_family="custom",
            steps=_draft_steps(),
            library_dir=tmp_path,
            code="MINE1",
        )
    assert exc.value.status == 409


def test_step_needs_a_duration_or_distance():
    with pytest.raises(SessionWriteError):
        build_canonical(
            code="CUS1",
            human_name="bad",
            method_family="custom",
            steps=[{"role": "work", "zone": "Z3"}],
        )

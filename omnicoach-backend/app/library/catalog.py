"""Thin wrapper over the canonical running workout library.

The heavy lifting is done by `workout_library_reader.py`, provided by the
project supervisor. This module only:
  * loads it once,
  * turns workouts into a compact, LLM-readable catalog,
  * exposes the list of valid codes used to constrain the agent's output.

The library DATA (the `converted/` folder) is licensed personal-use only by its
provider and is therefore never bundled here — point LIBRARY_PATH at it.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.library.workout_library_reader import WorkoutLibrary


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    family: str
    duration_min: int | None
    distance_km: float | None
    zones: tuple[str, ...]

    def to_line(self) -> str:
        """One compact line per workout — this is what the LLM reads.

        Roughly 25 tokens instead of the ~8k of the full JSON document.
        """
        size = (
            f"{self.duration_min} min"
            if self.duration_min
            else f"{self.distance_km} km" if self.distance_km else "?"
        )
        return f"{self.code} | {self.family} | {size} | zones {'+'.join(self.zones)}"


class Catalog:
    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(
                f"Workout library not found at {path}. Set LIBRARY_PATH to the "
                "'converted' folder of the canonical library."
            )
        self._lib = WorkoutLibrary.open(str(path))

    @property
    def codes(self) -> list[str]:
        return self._lib.list_codes()

    @property
    def reader(self):
        """The underlying WorkoutLibrary, for step-level expansion."""
        return self._lib

    def stats(self) -> dict:
        families: dict[str, int] = {}
        for code in self.codes:
            fam = self._lib.get(code).family
            families[fam] = families.get(fam, 0) + 1
        return {"workouts": len(self.codes), "families": families}

    def search(
        self,
        *,
        family: str | None = None,
        min_duration_min: int | None = None,
        max_duration_min: int | None = None,
        max_distance_km: float | None = None,
        required_zones: set[str] | None = None,
        include_unknown_duration: bool = False,
    ) -> list[CatalogEntry]:
        """Search the library.

        WARNING — the underlying reader computes `duration_min` as
        `duration_sec / 60`, and the 28 distance-based workouts (all the long-run
        families: RL, RLFF, RLMS, RLSP) carry `known_duration_sec = 0`. They
        therefore satisfy *any* `max_duration_min` filter: asking for "at most
        20 minutes" hands back a 32 km long run.

        So duration filters exclude unknown-duration workouts by default. Filter
        those by `max_distance_km` instead.
        """
        results = self._lib.search(
            family=family,
            min_duration_min=min_duration_min,
            max_duration_min=max_duration_min,
            max_distance_km=max_distance_km,
            required_zones=required_zones,
        )
        entries = [self._entry(w) for w in results]

        duration_filtered = (
            min_duration_min is not None or max_duration_min is not None
        )
        if duration_filtered and not include_unknown_duration:
            entries = [e for e in entries if e.duration_min]
        return entries

    def all_entries(self) -> list[CatalogEntry]:
        return [self._entry(self._lib.get(c)) for c in self.codes]

    def _entry(self, w) -> CatalogEntry:
        return CatalogEntry(
            code=w.code,
            family=w.family,
            duration_min=round(w.duration_sec / 60) if w.duration_sec else None,
            distance_km=round(w.distance_m / 1000, 1) if w.distance_m else None,
            zones=tuple(sorted(w.zones)),
        )


@lru_cache
def get_catalog(path: str) -> Catalog:
    return Catalog(Path(path))

#!/usr/bin/env python3
"""Utilities for reading, querying, describing, and extending the canonical
running-workout JSON library.

The module uses only the Python standard library. It accepts either:
  * a directory containing the workout JSON files; or
  * the ZIP archive distributed with the library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

REQUIRED_TOP_LEVEL = {
    "schema_version", "workout_key", "name", "sport", "classification",
    "prescription", "source", "validation", "intensity_model"
}


def natural_key(value: str):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", value)]


def canonical_code(name: str, filename: str | None = None) -> str:
    """Normalize the known RCl/RCI source-name ambiguity."""
    code = name
    if re.fullmatch(r"RCl\d+", code or ""):
        code = "RCI" + code[3:]
    if filename and re.fullmatch(r"rci\d+\.json", filename.lower()):
        code = "RCI" + re.search(r"\d+", filename).group(0)
    return code


def family_from_code(code: str) -> str:
    if code == "RLMS":
        return "RLMS"
    if code.startswith("RTa"):
        return "RTa"
    match = re.match(r"([A-Za-z]+)", code)
    return match.group(1) if match else code


def find_library_directory(path: Path) -> Path:
    """Locate the directory that directly contains index.json and workouts."""
    path = path.resolve()
    candidates = [path, path / "converted"]
    candidates.extend(p.parent for p in path.rglob("index.json"))
    for candidate in candidates:
        if (candidate / "index.json").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate index.json under {path}")


def validate_minimal(workout: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL - workout.keys())
    if missing:
        errors.append(f"Missing top-level fields: {', '.join(missing)}")
    if workout.get("sport") != "running":
        errors.append("sport must be 'running'")
    if not isinstance(workout.get("prescription", {}).get("steps"), list):
        errors.append("prescription.steps must be a list")
    if not workout.get("workout_key"):
        errors.append("workout_key must be non-empty")
    return errors


def iter_atomic_steps(items: list[dict[str, Any]], multiplier: int = 1) -> Iterator[tuple[dict[str, Any], int]]:
    """Yield atomic steps and their execution multipliers.

    A count-based repeat remains compact in JSON. The multiplier tells callers
    how many times each nested atomic step is executed.
    """
    for item in items:
        if item.get("kind") == "repeat":
            count = item.get("condition", {}).get("count")
            if isinstance(count, int) and count > 0:
                yield from iter_atomic_steps(item.get("steps", []), multiplier * count)
            else:
                yield from iter_atomic_steps(item.get("steps", []), multiplier)
        elif item.get("kind") == "step":
            yield item, multiplier


def expand_steps(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return an execution-order list with count-based repeats expanded."""
    expanded: list[dict[str, Any]] = []
    for item in items:
        if item.get("kind") == "repeat":
            count = item.get("condition", {}).get("count")
            if not isinstance(count, int) or count < 1:
                raise ValueError("Cannot expand a repeat without a positive count")
            block = expand_steps(item.get("steps", []))
            for repetition in range(1, count + 1):
                for step in block:
                    copy = dict(step)
                    copy["repeat_iteration"] = repetition
                    expanded.append(copy)
        elif item.get("kind") == "step":
            expanded.append(dict(item))
    return expanded


def step_zone(step: dict[str, Any]) -> str | None:
    target = step.get("target") or {}
    if target.get("type") == "provider_zone":
        return target.get("zone_code")
    if target.get("type") == "provider_zone_range":
        return f'{target.get("zone_low")}-{target.get("zone_high")}'
    if target.get("type") == "rest":
        return "REST"
    return None


@dataclass
class WorkoutRecord:
    code: str
    file_name: str
    document: dict[str, Any]

    @property
    def family(self) -> str:
        return family_from_code(self.code)

    @property
    def duration_sec(self) -> float:
        return float(self.document.get("prescription", {}).get("known_duration_sec") or 0)

    @property
    def distance_m(self) -> float:
        return float(self.document.get("prescription", {}).get("known_distance_m") or 0)

    @property
    def zones(self) -> set[str]:
        return {
            zone for step, _ in iter_atomic_steps(self.document["prescription"]["steps"])
            if (zone := step_zone(step)) is not None
        }


class WorkoutLibrary:
    def __init__(self, records: dict[str, WorkoutRecord], index: dict[str, Any]):
        self.records = records
        self.index = index

    @classmethod
    def from_directory(cls, path: str | Path, strict: bool = True) -> "WorkoutLibrary":
        root = find_library_directory(Path(path))
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        records: dict[str, WorkoutRecord] = {}
        for entry in index.get("workouts", []):
            file_name = entry["json_file"]
            document = json.loads((root / file_name).read_text(encoding="utf-8"))
            errors = validate_minimal(document)
            if errors and strict:
                raise ValueError(f"{file_name}: {'; '.join(errors)}")
            code = canonical_code(document.get("name", Path(file_name).stem), file_name)
            if code in records:
                raise ValueError(f"Duplicate canonical code: {code}")
            records[code] = WorkoutRecord(code, file_name, document)
        return cls(records, index)

    @classmethod
    def from_zip(cls, path: str | Path, strict: bool = True) -> "WorkoutLibrary":
        # Callers that need long-lived extraction may prefer extracting once and
        # using from_directory. This convenience method loads all documents in memory.
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            index_names = [name for name in names if name.endswith("/converted/index.json") or name == "converted/index.json"]
            if len(index_names) != 1:
                raise ValueError("Expected exactly one converted/index.json in archive")
            index_name = index_names[0]
            prefix = index_name.rsplit("index.json", 1)[0]
            index = json.loads(archive.read(index_name).decode("utf-8"))
            records: dict[str, WorkoutRecord] = {}
            for entry in index.get("workouts", []):
                file_name = entry["json_file"]
                document = json.loads(archive.read(prefix + file_name).decode("utf-8"))
                errors = validate_minimal(document)
                if errors and strict:
                    raise ValueError(f"{file_name}: {'; '.join(errors)}")
                code = canonical_code(document.get("name", Path(file_name).stem), file_name)
                if code in records:
                    raise ValueError(f"Duplicate canonical code: {code}")
                records[code] = WorkoutRecord(code, file_name, document)
        return cls(records, index)

    @classmethod
    def open(cls, path: str | Path, strict: bool = True) -> "WorkoutLibrary":
        path = Path(path)
        return cls.from_zip(path, strict) if path.suffix.lower() == ".zip" else cls.from_directory(path, strict)

    def get(self, code: str) -> WorkoutRecord:
        normalized = canonical_code(code)
        try:
            return self.records[normalized]
        except KeyError as exc:
            raise KeyError(f"Unknown workout code: {code}") from exc

    def list_codes(self) -> list[str]:
        return sorted(self.records, key=natural_key)

    def search(
        self,
        *,
        family: str | None = None,
        required_zones: set[str] | None = None,
        min_duration_min: float | None = None,
        max_duration_min: float | None = None,
        min_distance_km: float | None = None,
        max_distance_km: float | None = None,
    ) -> list[WorkoutRecord]:
        results: list[WorkoutRecord] = []
        for record in self.records.values():
            if family and record.family != family:
                continue
            if required_zones and not required_zones.issubset(record.zones):
                continue
            duration_min = record.duration_sec / 60.0
            distance_km = record.distance_m / 1000.0
            if min_duration_min is not None and duration_min < min_duration_min:
                continue
            if max_duration_min is not None and duration_min > max_duration_min:
                continue
            if min_distance_km is not None and distance_km < min_distance_km:
                continue
            if max_distance_km is not None and distance_km > max_distance_km:
                continue
            results.append(record)
        return sorted(results, key=lambda r: natural_key(r.code))


def rebuild_index(directory: str | Path) -> dict[str, Any]:
    """Rebuild index.json after adding or updating workout files."""
    root = Path(directory)
    if root.name != "converted" and (root / "converted").is_dir():
        root = root / "converted"
    entries = []
    seen_codes: set[str] = set()
    seen_keys: set[str] = set()
    for path in sorted(root.glob("*.json")):
        if path.name == "index.json":
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_minimal(doc)
        if errors:
            raise ValueError(f"{path.name}: {'; '.join(errors)}")
        code = canonical_code(doc["name"], path.name)
        if code in seen_codes:
            raise ValueError(f"Duplicate code: {code}")
        if doc["workout_key"] in seen_keys:
            raise ValueError(f"Duplicate workout_key: {doc['workout_key']}")
        seen_codes.add(code)
        seen_keys.add(doc["workout_key"])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append({
            "workout_key": doc["workout_key"],
            "name": code,
            "sport": doc["sport"],
            "method_family": doc.get("classification", {}).get("method_family"),
            "json_file": path.name,
            "source_fit": doc.get("source", {}).get("original_filename"),
            "source_url": doc.get("source", {}).get("original_url"),
            "normalized_json_sha256": digest,
            "zone_normalization": doc.get("validation", {}).get("zone_normalization", {}),
            "warnings": doc.get("validation", {}).get("warnings", []),
        })
    entries.sort(key=lambda item: natural_key(item["name"]))
    index = {
        "schema_version": "1.2.0",
        "session_count": len(entries),
        "workouts": entries,
    }
    (root / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", help="Library directory or ZIP archive")
    parser.add_argument("--list", action="store_true", help="List canonical workout codes")
    parser.add_argument("--show", metavar="CODE", help="Print one workout as JSON")
    parser.add_argument("--family", help="Filter by family code, e.g. RF or RCI")
    parser.add_argument("--zones", nargs="*", help="Require these targets, e.g. Z1 Z3")
    parser.add_argument("--min-duration", type=float, help="Minimum known duration in minutes")
    parser.add_argument("--max-duration", type=float, help="Maximum known duration in minutes")
    args = parser.parse_args()

    library = WorkoutLibrary.open(args.library)
    if args.show:
        print(json.dumps(library.get(args.show).document, indent=2, ensure_ascii=False))
        return 0

    results = library.search(
        family=args.family,
        required_zones=set(args.zones or []),
        min_duration_min=args.min_duration,
        max_duration_min=args.max_duration,
    )
    if args.list or args.family or args.zones or args.min_duration or args.max_duration:
        for record in results if not args.list else [library.records[c] for c in library.list_codes()]:
            print(f"{record.code:6} {record.duration_sec/60:6.1f} min {record.distance_m/1000:6.2f} km {','.join(sorted(record.zones))}")
        return 0

    print(f"Loaded {len(library.records)} workouts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

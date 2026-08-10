"""Pace zone calculator based on reference performance (VDOT model) and athlete goals.

Given a reference race time (e.g. 10k in 47:30) OR athlete context (goal, level, weeks),
calculates all training zones:
- Recovery pace (very easy)
- Tempo (lactate threshold)
- 5K race pace
- Marathon pace
- VO2 Max
- Rep pace (short fast repeats)

Uses the VDOT framework from Jack Daniels' Running Formula, adapted for specific goals.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class PaceZone:
    """Training pace zone with min/km and example range."""

    name: str
    min_per_km: float
    description: str

    def format(self) -> str:
        """Format as MM:SS per km."""
        minutes = int(self.min_per_km)
        seconds = int((self.min_per_km - minutes) * 60)
        return f"{minutes}:{seconds:02d}"


# Goal type definitions
Goal = Literal["5K", "10K", "Half-Marathon", "Marathon", "Triathlon Sprint", "Triathlon Olympic", "Ultramarathon"]
Level = Literal["beginner", "intermediate", "advanced"]


# Reference times for goals by level (in min:sec format)
GOAL_REFERENCE_TIMES: dict[Goal, dict[Level, str]] = {
    "5K": {
        "beginner": "30:00",
        "intermediate": "22:00",
        "advanced": "18:00",
    },
    "10K": {
        "beginner": "65:00",
        "intermediate": "47:30",
        "advanced": "38:00",
    },
    "Half-Marathon": {
        "beginner": "2:15:00",
        "intermediate": "1:50:00",
        "advanced": "1:32:00",
    },
    "Marathon": {
        "beginner": "5:00:00",
        "intermediate": "4:15:00",
        "advanced": "3:30:00",
    },
    "Triathlon Sprint": {
        "beginner": "1:40:00",
        "intermediate": "1:25:00",
        "advanced": "1:15:00",
    },
    "Triathlon Olympic": {
        "beginner": "3:00:00",
        "intermediate": "2:30:00",
        "advanced": "2:10:00",
    },
    "Ultramarathon": {
        "beginner": "10:00:00",
        "intermediate": "8:30:00",
        "advanced": "7:00:00",
    },
}


class PaceCalculator:
    """Calculate training zones from reference performance or athlete goal.

    Input options:
    1. Reference string: "10 km in 47:30" or "5k in 22:10" or "marathon in 3:45"
    2. Goal-based: goal_type="Half-Marathon", level="intermediate", weeks_to_event=12
    
    Output: All training paces (recovery, tempo, 5k, marathon, etc.)
    """

    # Named race distances (km) — lets athletes write "half marathon in 1:22:00".
    NAMED_DISTANCES = {
        "marathon": 42.195,
        "half marathon": 21.0975,
        "half": 21.0975,
        "semi": 21.0975,          # French: semi-marathon
        "semi-marathon": 21.0975,
    }

    @staticmethod
    def parse_reference(reference_str: str) -> tuple[float, float] | None:
        """Parse a reference performance → (distance_km, time_minutes).

        Handles, case-insensitively:
        - "10 km in 47:30"          (MM:SS)
        - "5k in 22:10"
        - "half marathon in 1:22:00" (H:MM:SS + named distance)
        - "marathon in 3:45:00"
        - "21.1 km in 1:22:00"
        Returns None if it cannot be parsed (callers degrade gracefully).
        """
        if not reference_str or not reference_str.strip():
            return None
        text = reference_str.lower().strip()

        # --- time: H:MM:SS or MM:SS -----------------------------------------
        tmatch = re.search(r"in\s*(\d+):(\d+)(?::(\d+))?", text)
        if not tmatch:
            return None
        a, b, c = tmatch.group(1), tmatch.group(2), tmatch.group(3)
        if c is not None:                       # H:MM:SS
            time_minutes = int(a) * 60 + int(b) + int(c) / 60
        else:                                   # MM:SS
            time_minutes = int(a) + int(b) / 60

        # --- distance: named first, then numeric ----------------------------
        distance_km = None
        for name in sorted(PaceCalculator.NAMED_DISTANCES, key=len, reverse=True):
            if name in text:
                distance_km = PaceCalculator.NAMED_DISTANCES[name]
                break

        if distance_km is None:
            dmatch = re.search(r"(\d+(?:\.\d+)?)\s*(km|k|mile|mi|m)?", text)
            if not dmatch:
                return None
            raw = float(dmatch.group(1))
            unit = dmatch.group(2) or ""
            if unit in ("mile", "mi"):
                distance_km = raw * 1.60934
            elif unit in ("k", "km"):
                distance_km = raw
            elif unit == "m" or raw > 100:      # metres
                distance_km = raw / 1000
            else:
                distance_km = raw

        if not distance_km or time_minutes <= 0:
            return None
        return distance_km, time_minutes

    @staticmethod
    def calculate_vdot(distance_km: float, time_minutes: float) -> float:
        """Calculate equivalent VDOT from race performance.

        For simplicity, we store the race pace itself (in min/km) as our reference.
        """
        pace_min_per_km = time_minutes / distance_km
        return pace_min_per_km

    @staticmethod
    def calculate_zones_from_vdot(race_pace_min_per_km: float) -> dict[str, PaceZone]:
        """Calculate all training zones from race pace.
        
        Uses race pace (min/km) as the reference and applies deltas for each zone.
        Based on empirical running physiology.
        """
        # Define zone paces as deltas from race pace (negative = faster, positive = slower)
        # These deltas are in minutes per km
        zones_config = {
            "recovery": {
                "delta": 1.1,  # 1:06 min slower than race pace
                "description": "Very easy, active recovery days"
            },
            "tempo": {
                "delta": -0.25,  # 0:15 min faster than race pace
                "description": "Lactate threshold, 15-30 min repeats"
            },
            "threshold_5k": {
                "delta": -0.35,  # 0:21 min faster than race pace
                "description": "5K race intensity, 5-15 min repeats"
            },
            "vo2_max": {
                "delta": -0.75,  # 0:45 min faster than race pace
                "description": "Max aerobic capacity, 3-5 min repeats"
            },
            "rep": {
                "delta": -1.0,  # 1:00 min faster than race pace
                "description": "Short fast repeats, 200m-1000m"
            },
            "marathon": {
                "delta": 0.25,  # 0:15 min slower than race pace
                "description": "Long-distance running pace"
            },
        }
        
        zones = {}
        for zone_name, config in zones_config.items():
            pace_min_per_km = race_pace_min_per_km + config["delta"]
            # Ensure pace is reasonable (positive and realistic)
            pace_min_per_km = max(1.5, min(15.0, pace_min_per_km))
            
            zones[zone_name] = PaceZone(
                name=zone_name.replace("_", " ").title(),
                min_per_km=pace_min_per_km,
                description=config["description"],
            )
        
        return zones

    @classmethod
    def from_reference(cls, reference_str: str) -> dict[str, PaceZone] | None:
        """Single entry point: reference string → training zones.

        Returns dict of PaceZone objects keyed by zone name.
        Returns None if parsing fails.
        """
        parsed = cls.parse_reference(reference_str)
        if parsed is None:
            return None

        distance_km, time_minutes = parsed
        vdot = cls.calculate_vdot(distance_km, time_minutes)
        zones = cls.calculate_zones_from_vdot(vdot)

        return zones

    @classmethod
    def from_goal(
        cls,
        goal: Goal,
        level: Level = "intermediate",
        weeks_to_event: int | None = None,
    ) -> dict[str, PaceZone] | None:
        """Calculate zones from an athlete's goal.
        
        Args:
            goal: Type of goal (e.g., "Half-Marathon", "Triathlon Olympic")
            level: Athlete level (beginner, intermediate, advanced)
            weeks_to_event: Time until the event (for future adjustments)
        
        Returns: Dict of training zones or None if goal not found.
        """
        if goal not in GOAL_REFERENCE_TIMES:
            return None

        # Get reference time for this goal and level
        reference_str = GOAL_REFERENCE_TIMES[goal][level]
        
        # Parse distance from goal type
        goal_distances = {
            "5K": 5.0,
            "10K": 10.0,
            "Half-Marathon": 21.1,
            "Marathon": 42.2,
            "Triathlon Sprint": 10.0,  # 750m swim + 20km bike + 5km run (approx)
            "Triathlon Olympic": 10.0,  # Using 10k equivalent for running
            "Ultramarathon": 80.0,
        }
        
        distance_km = goal_distances.get(goal, 10.0)
        
        # Parse reference time
        pattern = r"(\d+):(\d+):(\d+)|(\d+):(\d+)"
        match = re.search(pattern, reference_str)
        
        if not match:
            return None
        
        if match.group(1):  # HH:MM:SS format
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = int(match.group(3))
            time_minutes = hours * 60 + minutes + seconds / 60
        else:  # MM:SS format
            minutes = int(match.group(4))
            seconds = int(match.group(5))
            time_minutes = minutes + seconds / 60
        
        vdot = cls.calculate_vdot(distance_km, time_minutes)
        zones = cls.calculate_zones_from_vdot(vdot)
        
        return zones


def calculate_pace_zones_for_context(
    reference_str: str | None = None,
    goal: Goal | None = None,
    level: Level = "intermediate",
) -> dict[str, PaceZone] | None:
    """Helper to calculate pace zones from either a reference string or a goal.

    Tries reference_str first, then falls back to goal-based calculation.
    Returns None if both are unavailable or unparseable.
    """
    if reference_str:
        zones = PaceCalculator.from_reference(reference_str)
        if zones:
            return zones
    
    if goal:
        zones = PaceCalculator.from_goal(goal, level=level)
        if zones:
            return zones
    
    return None


# Example usage
if __name__ == "__main__":
    print("=== PAC ZONES CALCULATOR ===\n")
    
    # Example 1: Using reference performance
    print("1. Reference-based (10 km in 47:30):")
    zones = PaceCalculator.from_reference("10 km in 47:30")
    if zones:
        for zone_name, zone in zones.items():
            print(f"   {zone.name:15} {zone.format()} /km")
    print()
    
    # Example 2: Using goal-based approach for intermediate athlete
    print("2. Goal-based approach (Half-Marathon, Intermediate):")
    zones = PaceCalculator.from_goal("Half-Marathon", level="intermediate")
    if zones:
        for zone_name, zone in zones.items():
            print(f"   {zone.name:15} {zone.format()} /km")
    print()
    
    # Example 3: Marathon for advanced athlete
    print("3. Goal-based approach (Marathon, Advanced):")
    zones = PaceCalculator.from_goal("Marathon", level="advanced")
    if zones:
        for zone_name, zone in zones.items():
            print(f"   {zone.name:15} {zone.format()} /km")
    print()
    
    # Example 4: All available goals for intermediate level
    print("4. Available goals for Intermediate athletes:\n")
    for goal in [
        "5K",
        "10K",
        "Half-Marathon",
        "Marathon",
        "Triathlon Sprint",
        "Triathlon Olympic",
        "Ultramarathon",
    ]:
        zones = PaceCalculator.from_goal(goal, level="intermediate")
        if zones:
            recovery = zones.get("recovery")
            if recovery:
                print(
                    f"   {goal:20} → Recovery: {recovery.format()} /km"
                )


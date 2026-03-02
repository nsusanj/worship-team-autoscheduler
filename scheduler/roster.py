from __future__ import annotations

import sys
from datetime import date
from typing import Optional

from .models import Config, Pin, RosterSlot, Volunteer, SKILL_ORDER


def build_roster(
    config: Config,
    volunteers: list[Volunteer],
    pins: list[Pin],
) -> list[RosterSlot]:
    """Build the full volunteer roster using OR-Tools CP-SAT solver.

    Falls back to a greedy heuristic if OR-Tools is unavailable.
    """
    try:
        from ortools.sat.python import cp_model  # noqa: F401
        return _solve_with_ortools(config, volunteers, pins)
    except ImportError:
        print(
            "Warning: ortools not installed. Falling back to greedy solver.",
            file=sys.stderr,
        )
        return _solve_greedy(config, volunteers, pins)


# ---------------------------------------------------------------------------
# OR-Tools CP-SAT solver
# ---------------------------------------------------------------------------

def _solve_with_ortools(
    config: Config,
    volunteers: list[Volunteer],
    pins: list[Pin],
) -> list[RosterSlot]:
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()

    sundays = config.sundays
    locations = config.locations
    roles = config.roles
    vol_names = [v.name for v in volunteers]
    vol_index: dict[str, int] = {v.name: i for i, v in enumerate(volunteers)}

    # ------------------------------------------------------------------
    # Index pins for fast lookup
    # ------------------------------------------------------------------
    # roster_pins[(date, location, role)] = volunteer_name
    roster_pins: dict[tuple[date, str, str], str] = {}
    for pin in pins:
        if pin.volunteer is not None and pin.date and pin.location and pin.role:
            roster_pins[(pin.date, pin.location, pin.role)] = pin.volunteer

    # ------------------------------------------------------------------
    # Decision variables
    # instrument[vi, si, li, ri] = 1 if volunteer vi plays role ri at location li on sunday si
    # vocalist[vi, si, li] = 1 if volunteer vi is a vocalist at location li on sunday si
    # ------------------------------------------------------------------
    instrument: dict[tuple[int, int, int, int], cp_model.IntVar] = {}
    vocalist: dict[tuple[int, int, int], cp_model.IntVar] = {}

    for si, sunday in enumerate(sundays):
        for li, loc in enumerate(locations):
            for ri, role in enumerate(roles):
                for vi, vol in enumerate(volunteers):
                    # Skip ineligible assignments up front
                    if not vol.can_fill_role(role):
                        continue
                    if not vol.is_available(sunday):
                        continue
                    if loc == "Auditorium" and not vol.auditorium_eligible:
                        continue
                    key = (vi, si, li, ri)
                    instrument[key] = model.NewBoolVar(f"instr_{vi}_{si}_{li}_{ri}")

            for vi, vol in enumerate(volunteers):
                if not vol.can_sing:
                    continue
                if not vol.is_available(sunday):
                    continue
                if loc == "Auditorium" and not vol.auditorium_eligible:
                    continue
                key = (vi, si, li)
                vocalist[key] = model.NewBoolVar(f"vocal_{vi}_{si}_{li}")

    # ------------------------------------------------------------------
    # Hard constraints
    # ------------------------------------------------------------------

    for si, sunday in enumerate(sundays):
        for li, loc in enumerate(locations):

            # 1. Each instrument role filled by exactly 1 eligible volunteer
            for ri, role in enumerate(roles):
                slot_vars = [
                    instrument[(vi, si, li, ri)]
                    for vi in range(len(volunteers))
                    if (vi, si, li, ri) in instrument
                ]
                if not slot_vars:
                    print(
                        f"Warning: no eligible volunteers for {role} at {loc} on {sunday}.",
                        file=sys.stderr,
                    )
                    model.Add(cp_model.LinearExpr.Sum([]) == 1)  # infeasible — will be caught
                else:
                    model.AddExactlyOne(slot_vars)

            # 2. Exactly vocalists_per_location singers at each location
            vocal_vars = [
                vocalist[(vi, si, li)]
                for vi in range(len(volunteers))
                if (vi, si, li) in vocalist
            ]
            if len(vocal_vars) < config.vocalists_per_location:
                print(
                    f"Warning: fewer eligible singers ({len(vocal_vars)}) than required "
                    f"({config.vocalists_per_location}) at {loc} on {sunday}.",
                    file=sys.stderr,
                )
            model.Add(cp_model.LinearExpr.Sum(vocal_vars) == config.vocalists_per_location)

            # 3. A volunteer plays at most one instrument role per location per Sunday
            for vi in range(len(volunteers)):
                instr_vars = [
                    instrument[(vi, si, li, ri)]
                    for ri in range(len(roles))
                    if (vi, si, li, ri) in instrument
                ]
                if len(instr_vars) > 1:
                    model.Add(cp_model.LinearExpr.Sum(instr_vars) <= 1)

        # 4. A volunteer appears at most once per Sunday across both locations (no double-booking)
        for vi in range(len(volunteers)):
            all_day_vars: list[cp_model.IntVar] = []
            for li in range(len(locations)):
                for ri in range(len(roles)):
                    if (vi, si, li, ri) in instrument:
                        all_day_vars.append(instrument[(vi, si, li, ri)])
                if (vi, si, li) in vocalist:
                    all_day_vars.append(vocalist[(vi, si, li)])
            # Each service counts once; an instrumentalist who also sings is
            # counted as one service.  We model this by allowing the sum to be
            # up to (number of possible combos), but we must prevent assignment
            # to two *different locations* on the same Sunday.
            # Enforce: assigned to at most 1 location per Sunday.
            for li in range(len(locations)):
                loc_vars: list[cp_model.IntVar] = []
                for ri in range(len(roles)):
                    if (vi, si, li, ri) in instrument:
                        loc_vars.append(instrument[(vi, si, li, ri)])
                if (vi, si, li) in vocalist:
                    loc_vars.append(vocalist[(vi, si, li)])
                # presence at this location
                if loc_vars:
                    is_present_loc = model.NewBoolVar(f"present_{vi}_{si}_{li}")
                    model.AddMaxEquality(is_present_loc, loc_vars)
            # Across locations: at most 1
            loc_presence: list[cp_model.IntVar] = []
            for li in range(len(locations)):
                any_instr = [
                    instrument[(vi, si, li, ri)]
                    for ri in range(len(roles))
                    if (vi, si, li, ri) in instrument
                ]
                any_vocal = [vocalist[(vi, si, li)]] if (vi, si, li) in vocalist else []
                combined = any_instr + any_vocal
                if combined:
                    is_present = model.NewBoolVar(f"xpresent_{vi}_{si}_{li}")
                    model.AddMaxEquality(is_present, combined)
                    loc_presence.append(is_present)
            if len(loc_presence) > 1:
                model.Add(cp_model.LinearExpr.Sum(loc_presence) <= 1)

    # ------------------------------------------------------------------
    # Apply pins (hard locks)
    # ------------------------------------------------------------------
    for (pin_date, pin_loc, pin_role), pin_vol in roster_pins.items():
        if pin_vol not in vol_index:
            print(
                f"Warning: pinned volunteer '{pin_vol}' not found. Skipping pin.",
                file=sys.stderr,
            )
            continue
        si = next((i for i, d in enumerate(sundays) if d == pin_date), None)
        if si is None:
            print(f"Warning: pin date {pin_date} not in scheduling block. Skipping.", file=sys.stderr)
            continue
        li = next((i for i, l in enumerate(locations) if l == pin_loc), None)
        ri = next((i for i, r in enumerate(roles) if r == pin_role), None)
        if li is None or ri is None:
            print(
                f"Warning: pin location '{pin_loc}' or role '{pin_role}' not recognised. Skipping.",
                file=sys.stderr,
            )
            continue
        vi = vol_index[pin_vol]
        key = (vi, si, li, ri)
        if key not in instrument:
            print(
                f"Warning: pinned assignment ({pin_vol}, {pin_loc}, {pin_role}, {pin_date}) "
                "is not feasible (volunteer ineligible/blocked). Skipping.",
                file=sys.stderr,
            )
        else:
            model.Add(instrument[key] == 1)

    # ------------------------------------------------------------------
    # Soft constraints — minimise weighted penalty
    # ------------------------------------------------------------------
    penalty_terms: list[cp_model.IntVar] = []

    # (a) Deviation from target frequency
    # Count how many Sundays each volunteer is scheduled (instrument or vocalist)
    # A volunteer who plays and sings on the same Sunday counts as 1 service.
    FREQ_PENALTY_WEIGHT = 10
    for vi, vol in enumerate(volunteers):
        target_sundays = round(vol.target_frequency * len(sundays))
        # Binary var: is this volunteer scheduled on Sunday si?
        scheduled_per_sunday: list[cp_model.IntVar] = []
        for si in range(len(sundays)):
            day_vars: list[cp_model.IntVar] = []
            for li in range(len(locations)):
                for ri in range(len(roles)):
                    if (vi, si, li, ri) in instrument:
                        day_vars.append(instrument[(vi, si, li, ri)])
                if (vi, si, li) in vocalist:
                    day_vars.append(vocalist[(vi, si, li)])
            if day_vars:
                is_scheduled = model.NewBoolVar(f"sched_{vi}_{si}")
                model.AddMaxEquality(is_scheduled, day_vars)
                scheduled_per_sunday.append(is_scheduled)
            else:
                scheduled_per_sunday.append(model.NewConstant(0))

        total_scheduled = model.NewIntVar(0, len(sundays), f"total_{vi}")
        model.Add(total_scheduled == cp_model.LinearExpr.Sum(scheduled_per_sunday))

        # abs(total - target) penalty
        diff = model.NewIntVar(-len(sundays), len(sundays), f"diff_{vi}")
        model.Add(diff == total_scheduled - target_sundays)
        abs_diff = model.NewIntVar(0, len(sundays), f"absdiff_{vi}")
        model.AddAbsEquality(abs_diff, diff)
        scaled = model.NewIntVar(0, FREQ_PENALTY_WEIGHT * len(sundays), f"freq_pen_{vi}")
        model.Add(scaled == FREQ_PENALTY_WEIGHT * abs_diff)
        penalty_terms.append(scaled)

    # (b) Skill level below auditorium threshold
    SKILL_PENALTY_WEIGHT = 5
    aud_li = next((i for i, l in enumerate(locations) if l == "Auditorium"), None)
    if aud_li is not None:
        for vi, vol in enumerate(volunteers):
            if SKILL_ORDER[vol.skill_level] < SKILL_ORDER[config.auditorium_min_skill]:
                for si in range(len(sundays)):
                    day_aud_vars: list[cp_model.IntVar] = []
                    for ri in range(len(roles)):
                        if (vi, si, aud_li, ri) in instrument:
                            day_aud_vars.append(instrument[(vi, si, aud_li, ri)])
                    if (vi, si, aud_li) in vocalist:
                        day_aud_vars.append(vocalist[(vi, si, aud_li)])
                    for var in day_aud_vars:
                        penalty_terms.append(
                            _scaled_bool(model, var, SKILL_PENALTY_WEIGHT, f"skill_{vi}_{si}")
                        )

    # (c) Preferred instrument penalty — soft-penalise non-preferred assignments
    PREF_INSTRUMENT_PENALTY_WEIGHT = 4
    for vi, vol in enumerate(volunteers):
        if vol.preferred_instruments:
            non_preferred = [r for r in vol.can_play if r not in vol.preferred_instruments]
            for ri, role in enumerate(roles):
                if role not in non_preferred:
                    continue
                for si in range(len(sundays)):
                    for li in range(len(locations)):
                        key = (vi, si, li, ri)
                        if key in instrument:
                            penalty_terms.append(
                                _scaled_bool(
                                    model,
                                    instrument[key],
                                    PREF_INSTRUMENT_PENALTY_WEIGHT,
                                    f"pref_{vi}_{si}_{li}_{ri}",
                                )
                            )

    # (d) Encourage even spread — graduated 3-week window penalty
    SPREAD_WEIGHTS = {1: 6, 2: 3, 3: 1}
    for vi, vol in enumerate(volunteers):
        scheduled_flags: list[cp_model.IntVar] = []
        for si in range(len(sundays)):
            day_vars = []
            for li in range(len(locations)):
                for ri in range(len(roles)):
                    if (vi, si, li, ri) in instrument:
                        day_vars.append(instrument[(vi, si, li, ri)])
                if (vi, si, li) in vocalist:
                    day_vars.append(vocalist[(vi, si, li)])
            if day_vars:
                flag = model.NewBoolVar(f"sflag_{vi}_{si}")
                model.AddMaxEquality(flag, day_vars)
            else:
                flag = model.NewConstant(0)
            scheduled_flags.append(flag)

        for gap, weight in SPREAD_WEIGHTS.items():
            for si in range(len(sundays) - gap):
                both = model.NewBoolVar(f"spread_{vi}_{si}_{gap}")
                model.AddMultiplicationEquality(both, [scheduled_flags[si], scheduled_flags[si + gap]])
                penalty_terms.append(
                    _scaled_bool(model, both, weight, f"spread_pen_{vi}_{si}_{gap}")
                )

    # Minimise total penalty
    total_penalty = model.NewIntVar(0, 10_000_000, "total_penalty")
    model.Add(total_penalty == cp_model.LinearExpr.Sum(penalty_terms))
    model.Minimize(total_penalty)

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(
            "Error: OR-Tools could not find a feasible roster. "
            "Check volunteer availability and constraints.",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Extract solution
    # ------------------------------------------------------------------
    slots: list[RosterSlot] = []
    for si, sunday in enumerate(sundays):
        for li, loc in enumerate(locations):
            # Determine which volunteers are vocalists this day-location
            vocal_set: set[int] = set()
            for vi in range(len(volunteers)):
                if (vi, si, li) in vocalist and solver.Value(vocalist[(vi, si, li)]):
                    vocal_set.add(vi)

            # Instrument assignments
            instr_assigned: set[int] = set()
            for ri, role in enumerate(roles):
                for vi, vol in enumerate(volunteers):
                    if (vi, si, li, ri) in instrument and solver.Value(instrument[(vi, si, li, ri)]):
                        also_sings = vi in vocal_set
                        slots.append(
                            RosterSlot(
                                date=sunday,
                                location=loc,
                                role=role,
                                volunteer_name=vol.name,
                                also_sings=also_sings,
                            )
                        )
                        instr_assigned.add(vi)

            # Pure vocalists (not also playing an instrument)
            for vi in vocal_set:
                if vi not in instr_assigned:
                    slots.append(
                        RosterSlot(
                            date=sunday,
                            location=loc,
                            role="vocalist",
                            volunteer_name=volunteers[vi].name,
                            also_sings=False,
                        )
                    )

    return slots


# ---------------------------------------------------------------------------
# Greedy fallback
# ---------------------------------------------------------------------------

def _solve_greedy(
    config: Config,
    volunteers: list[Volunteer],
    pins: list[Pin],
) -> list[RosterSlot]:
    """Simple greedy solver used when OR-Tools is unavailable."""
    sundays = config.sundays
    locations = config.locations
    roles = config.roles

    # Roster pin index
    roster_pins: dict[tuple[date, str, str], str] = {}
    for pin in pins:
        if pin.volunteer is not None and pin.date and pin.location and pin.role:
            roster_pins[(pin.date, pin.location, pin.role)] = pin.volunteer

    vol_map = {v.name: v for v in volunteers}
    assigned_count: dict[str, int] = {v.name: 0 for v in volunteers}
    last_assigned: dict[str, Optional[date]] = {v.name: None for v in volunteers}

    slots: list[RosterSlot] = []

    for sunday in sundays:
        # Track who is already assigned today (across all locations)
        assigned_today: set[str] = set()

        for loc in locations:
            # Determine which volunteers are vocalists this day
            vocal_set: set[str] = set()

            # Fill instrument roles first
            for role in roles:
                # Check for pin
                pinned_vol = roster_pins.get((sunday, loc, role))
                if pinned_vol:
                    vol = vol_map.get(pinned_vol)
                    if vol and vol.is_available(sunday) and pinned_vol not in assigned_today:
                        slots.append(
                            RosterSlot(date=sunday, location=loc, role=role, volunteer_name=pinned_vol)
                        )
                        assigned_today.add(pinned_vol)
                        assigned_count[pinned_vol] += 1
                        last_assigned[pinned_vol] = sunday
                        continue
                    elif pinned_vol:
                        print(
                            f"Warning: pinned {pinned_vol} for {role} at {loc} on {sunday} "
                            "is unavailable or double-booked. Using best available.",
                            file=sys.stderr,
                        )

                candidates = _greedy_candidates(
                    volunteers=volunteers,
                    role=role,
                    location=loc,
                    sunday=sunday,
                    assigned_today=assigned_today,
                    assigned_count=assigned_count,
                    last_assigned=last_assigned,
                    config=config,
                )
                if not candidates:
                    print(
                        f"Warning: no candidate for {role} at {loc} on {sunday}.",
                        file=sys.stderr,
                    )
                    continue
                chosen = candidates[0]
                slots.append(
                    RosterSlot(date=sunday, location=loc, role=role, volunteer_name=chosen.name)
                )
                assigned_today.add(chosen.name)
                assigned_count[chosen.name] += 1
                last_assigned[chosen.name] = sunday

            # Fill vocalist slots (3 per location)
            # Prefer instrumentalists who can sing first (to model combos)
            instr_singers = [
                name for name in assigned_today
                if loc in [s.location for s in slots if s.volunteer_name == name and s.date == sunday]
                and vol_map.get(name, Volunteer("", [], [], False, "intermediate", 0.5, [], False)).can_sing
            ]
            vocal_count = min(len(instr_singers), config.vocalists_per_location)
            for name in instr_singers[:vocal_count]:
                vocal_set.add(name)

            # Fill remaining vocalist slots from non-instrumentalists
            remaining_vocal = config.vocalists_per_location - len(vocal_set)
            vocal_candidates = _greedy_candidates(
                volunteers=volunteers,
                role="vocalist",
                location=loc,
                sunday=sunday,
                assigned_today=assigned_today,
                assigned_count=assigned_count,
                last_assigned=last_assigned,
                config=config,
            )
            for vc in vocal_candidates[:remaining_vocal]:
                slots.append(
                    RosterSlot(date=sunday, location=loc, role="vocalist", volunteer_name=vc.name)
                )
                vocal_set.add(vc.name)
                assigned_today.add(vc.name)
                assigned_count[vc.name] += 1
                last_assigned[vc.name] = sunday

            # Mark also_sings on instrumentalists who ended up in vocal_set
            for slot in slots:
                if (
                    slot.date == sunday
                    and slot.location == loc
                    and slot.role != "vocalist"
                    and slot.volunteer_name in vocal_set
                ):
                    slot.also_sings = True

    return slots


def _greedy_candidates(
    volunteers: list[Volunteer],
    role: str,
    location: str,
    sunday: date,
    assigned_today: set[str],
    assigned_count: dict[str, int],
    last_assigned: dict[str, Optional[date]],
    config: Config,
) -> list[Volunteer]:
    candidates = [
        v for v in volunteers
        if v.can_fill_role(role)
        and v.is_available(sunday)
        and v.name not in assigned_today
        and (location != "Auditorium" or v.auditorium_eligible)
    ]

    num_sundays = len(config.sundays)

    def sort_key(v: Volunteer):
        target = round(v.target_frequency * num_sundays)
        remaining = target - assigned_count[v.name]
        lu = last_assigned[v.name]
        days_since = (sunday - lu).days if lu else 999
        # Preferred instrument bonus: 1 if this role is preferred, 0 otherwise
        pref_bonus = 1 if (v.preferred_instruments and role in v.preferred_instruments) else 0
        # Prioritise: (1) most behind target, (2) preferred instrument, (3) longest since last, (4) skill
        return (-remaining, -pref_bonus, -days_since, -SKILL_ORDER[v.skill_level])

    candidates.sort(key=sort_key)
    return candidates


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _scaled_bool(model, var, weight: int, name: str):
    """Return a new IntVar equal to weight * var."""
    from ortools.sat.python import cp_model
    scaled = model.NewIntVar(0, weight, f"scaled_{name}")
    model.Add(scaled == weight * var)
    return scaled

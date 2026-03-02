from __future__ import annotations

import csv
import io
import sys
from datetime import date
from typing import Optional

from .models import Config, DaySetlist, RosterSlot, Schedule, Volunteer


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def write_csv(schedule: Schedule, config: Config, volunteers: list[Volunteer], path: Optional[str]) -> None:
    """Write the schedule to a CSV file (or stdout if path is None)."""
    rows = _build_rows(schedule, config)
    header = _csv_header(config)

    if path:
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Schedule written to {path}")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def _csv_header(config: Config) -> list[str]:
    vocalist_cols = [f"Vocalist{i + 1}" for i in range(config.vocalists_per_location)]
    song_cols = [f"Song{i + 1}" for i in range(config.songs_per_setlist)]
    return ["Date", "Location"] + [r.capitalize() for r in config.roles] + vocalist_cols + song_cols


def _build_rows(schedule: Schedule, config: Config) -> list[dict]:
    rows = []
    for sunday in config.sundays:
        setlist = schedule.setlist_for(sunday)
        songs = setlist.songs if setlist else []

        for loc in config.locations:
            row: dict[str, str] = {"Date": str(sunday), "Location": loc}

            roster = schedule.roster_for(sunday, loc)

            # Instrument columns
            for role in config.roles:
                slots = [r for r in roster if r.role == role]
                if slots:
                    name = slots[0].volunteer_name
                    row[role.capitalize()] = name + (" *" if slots[0].also_sings else "")
                else:
                    row[role.capitalize()] = ""

            # Vocalist columns — include instrument players who also sing
            vocalists: list[str] = []
            # First: instrumentalists who also sing (marked with also_sings)
            for slot in roster:
                if slot.also_sings and slot.role != "vocalist":
                    vocalists.append(slot.volunteer_name)
            # Then: pure vocalists
            for slot in roster:
                if slot.role == "vocalist":
                    vocalists.append(slot.volunteer_name)

            for i in range(config.vocalists_per_location):
                col = f"Vocalist{i + 1}"
                row[col] = vocalists[i] if i < len(vocalists) else ""

            # Song columns
            for i in range(config.songs_per_setlist):
                col = f"Song{i + 1}"
                row[col] = songs[i] if i < len(songs) else ""

            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Console (text table) output
# ---------------------------------------------------------------------------

def print_schedule(schedule: Schedule, config: Config, volunteers: list[Volunteer]) -> None:
    """Pretty-print the schedule to stdout."""
    try:
        from tabulate import tabulate
        _tabulate_output(schedule, config, volunteers, tabulate)
    except ImportError:
        _plain_output(schedule, config, volunteers)


def _tabulate_output(schedule, config, volunteers, tabulate_fn) -> None:
    rows = _build_rows(schedule, config)
    header = _csv_header(config)
    table_data = [[r.get(h, "") for h in header] for r in rows]

    print("\n=== SCHEDULE ===\n")
    print(tabulate_fn(table_data, headers=header, tablefmt="rounded_outline"))

    print("\n=== VOLUNTEER SUMMARY ===\n")
    _print_volunteer_summary(schedule, config, volunteers, tabulate_fn)


def _plain_output(schedule, config, volunteers) -> None:
    print("\n=== SCHEDULE ===\n")
    for sunday in config.sundays:
        setlist = schedule.setlist_for(sunday)
        songs = ", ".join(setlist.songs) if setlist else "N/A"
        print(f"  {sunday}  Songs: {songs}")
        for loc in config.locations:
            roster = schedule.roster_for(sunday, loc)
            parts = [f"{r.role}: {r.volunteer_name}" for r in roster]
            print(f"    [{loc}] {' | '.join(parts)}")

    print("\n=== VOLUNTEER SUMMARY ===\n")
    _print_volunteer_summary_plain(schedule, config, volunteers)


def _print_volunteer_summary(schedule, config, volunteers, tabulate_fn) -> None:
    rows = _volunteer_summary_rows(schedule, config, volunteers)
    print(tabulate_fn(rows, headers=["Volunteer", "Assigned", "Target", "Delta"], tablefmt="simple"))


def _print_volunteer_summary_plain(schedule, config, volunteers) -> None:
    rows = _volunteer_summary_rows(schedule, config, volunteers)
    print(f"{'Volunteer':<30} {'Assigned':>8} {'Target':>8} {'Delta':>6}")
    print("-" * 56)
    for row in rows:
        print(f"{row[0]:<30} {row[1]:>8} {row[2]:>8} {row[3]:>+6}")


def _volunteer_summary_rows(schedule, config, volunteers) -> list[tuple]:
    # Count distinct Sundays each volunteer is assigned (not double-counting instrument + vocal)
    sunday_per_vol: dict[str, set[date]] = {v.name: set() for v in volunteers}
    for slot in schedule.roster:
        sunday_per_vol[slot.volunteer_name].add(slot.date)

    rows = []
    for vol in sorted(volunteers, key=lambda v: v.name):
        assigned = len(sunday_per_vol[vol.name])
        delta = assigned - vol.target_sundays
        rows.append((vol.name, assigned, vol.target_sundays, f"{delta:+d}"))
    return rows

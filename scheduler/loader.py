from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml

from .models import Config, Pin, Song, Volunteer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _parse_date_list(values) -> list[date]:
    if not values:
        return []
    return [_parse_date(v) for v in values]


def _load_yaml(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"Error: file not found: {p}", file=sys.stderr)
        sys.exit(1)
    with open(p) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> Config:
    raw = _load_yaml(path)
    return Config(
        block_start=_parse_date(raw["block_start"]),
        num_sundays=int(raw["num_sundays"]),
        locations=list(raw["locations"]),
        roles=list(raw["roles"]),
        vocalists_per_location=int(raw["vocalists_per_location"]),
        song_cooldown_weeks=int(raw["song_cooldown_weeks"]),
        songs_per_setlist=int(raw["songs_per_setlist"]),
        target_new_songs_per_setlist=int(raw["target_new_songs_per_setlist"]),
        auditorium_skill_threshold=int(raw["auditorium_skill_threshold"]),
    )


def load_volunteers(path: str | Path) -> list[Volunteer]:
    raw = _load_yaml(path)
    volunteers: list[Volunteer] = []
    for entry in raw.get("volunteers", []):
        skill = int(entry.get("skill_level", 3))
        # Derive auditorium_eligible from skill_level if not explicitly set
        aud_eligible = entry.get("auditorium_eligible")
        if aud_eligible is None:
            aud_eligible = skill >= 3
        volunteers.append(
            Volunteer(
                name=str(entry["name"]),
                can_play=[r.strip() for r in (entry.get("can_play") or [])],
                can_sing=bool(entry.get("can_sing", False)),
                skill_level=skill,
                target_sundays=int(entry.get("target_sundays", 6)),
                blocked_dates=_parse_date_list(entry.get("blocked_dates")),
                auditorium_eligible=bool(aud_eligible),
            )
        )
    _validate_volunteers(volunteers)
    return volunteers


def load_songs(path: str | Path) -> list[Song]:
    raw = _load_yaml(path)
    songs: list[Song] = []
    for entry in raw.get("songs", []):
        status = str(entry.get("status", "established"))
        if status not in ("established", "new"):
            print(
                f"Warning: song '{entry['title']}' has unknown status '{status}', "
                "treating as established.",
                file=sys.stderr,
            )
            status = "established"
        songs.append(
            Song(
                title=str(entry["title"]),
                status=status,
                last_played=_parse_date(entry.get("last_played")),
            )
        )
    return songs


def load_pins(path: str | Path) -> list[Pin]:
    raw = _load_yaml(path)
    pins: list[Pin] = []
    for entry in raw.get("pins", []):
        d = _parse_date(entry["date"])
        # Determine if this is a song pin or a roster pin
        songs = entry.get("songs")
        volunteer = entry.get("volunteer")
        location = entry.get("location")
        role = entry.get("role")

        if songs is not None:
            # Song-only pin
            pins.append(Pin(date=d, location=None, role=None, volunteer=None, songs=list(songs)))
        elif volunteer is not None:
            # Roster pin — location and role are required
            if location is None or role is None:
                print(
                    f"Warning: roster pin for '{volunteer}' on {d} is missing location or role. Skipping.",
                    file=sys.stderr,
                )
                continue
            pins.append(Pin(date=d, location=location, role=role, volunteer=volunteer, songs=None))
        else:
            print(f"Warning: pin on {d} has neither 'songs' nor 'volunteer'. Skipping.", file=sys.stderr)
    return pins


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

VALID_ROLES = {"keys", "drums", "bass", "acoustic", "electric", "vocalist"}


def _validate_volunteers(volunteers: list[Volunteer]) -> None:
    names = set()
    for v in volunteers:
        if v.name in names:
            print(f"Warning: duplicate volunteer name '{v.name}'.", file=sys.stderr)
        names.add(v.name)
        for role in v.can_play:
            if role not in VALID_ROLES:
                print(
                    f"Warning: volunteer '{v.name}' lists unknown role '{role}' in can_play.",
                    file=sys.stderr,
                )
        if not (1 <= v.skill_level <= 5):
            print(
                f"Warning: volunteer '{v.name}' has skill_level {v.skill_level} outside 1–5.",
                file=sys.stderr,
            )

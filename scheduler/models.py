from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


SKILL_ORDER: dict[str, int] = {"beginner": 1, "intermediate": 2, "advanced": 3}


@dataclass
class Volunteer:
    name: str
    can_play: list[str]               # list of instrument roles (keys, drums, bass, acoustic, electric)
    preferred_instruments: list[str]  # subset of can_play; [] = no preference
    can_sing: bool
    skill_level: str                  # "beginner" | "intermediate" | "advanced"
    target_frequency: float           # 0.0–1.0 (fraction of Sundays desired)
    blocked_dates: list[date]
    auditorium_eligible: bool

    def can_fill_role(self, role: str) -> bool:
        """Return True if this volunteer can fill the given role.

        Role may be an instrument name or 'vocalist'.
        """
        if role == "vocalist":
            return self.can_sing
        return role in self.can_play

    def is_available(self, d: date) -> bool:
        return d not in self.blocked_dates


@dataclass
class Song:
    title: str
    status: str           # "established" | "new"
    last_played: Optional[date]

    def is_new(self) -> bool:
        return self.status == "new"


@dataclass
class Config:
    block_start: date
    num_sundays: int
    locations: list[str]
    roles: list[str]             # instrument roles only
    vocalists_per_location: int
    song_cooldown_weeks: int
    songs_per_setlist: int
    target_new_songs_per_setlist: int
    auditorium_min_skill: str    # "beginner" | "intermediate" | "advanced"

    @property
    def sundays(self) -> list[date]:
        from datetime import timedelta
        return [self.block_start + timedelta(weeks=i) for i in range(self.num_sundays)]


@dataclass
class RosterSlot:
    """A single volunteer assignment for one role at one location on one date."""
    date: date
    location: str
    role: str                    # instrument role or "vocalist"
    volunteer_name: str
    also_sings: bool = False     # True when an instrumentalist also fills a vocalist slot


@dataclass
class DaySetlist:
    date: date
    songs: list[str]             # song titles, length == config.songs_per_setlist


@dataclass
class Schedule:
    setlists: list[DaySetlist]
    roster: list[RosterSlot]

    def roster_for(self, d: date, location: str) -> list[RosterSlot]:
        return [r for r in self.roster if r.date == d and r.location == location]

    def setlist_for(self, d: date) -> Optional[DaySetlist]:
        for s in self.setlists:
            if s.date == d:
                return s
        return None


@dataclass
class Pin:
    """A pre-locked assignment provided by the user before the solver runs."""
    date: date
    location: Optional[str]      # None for song-only pins
    role: Optional[str]          # None for song-only pins
    volunteer: Optional[str]     # None for song-only pins
    songs: Optional[list[str]]   # set when pin locks songs for a Sunday

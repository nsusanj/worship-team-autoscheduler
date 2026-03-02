from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Optional

from .models import Config, DaySetlist, Pin, Song


def build_setlists(
    config: Config,
    songs: list[Song],
    pins: list[Pin],
    *,
    seed: Optional[int] = None,
) -> list[DaySetlist]:
    """Generate one setlist per Sunday in the scheduling block.

    Algorithm:
    1. Build a cooldown exclusion set for each Sunday based on last_played dates
       and previously chosen songs within the block.
    2. Apply song pins (locked songs for a given Sunday).
    3. Fill remaining slots, targeting ~target_new_songs_per_setlist new songs,
       then filling the rest with established songs.
    4. Songs chosen in earlier weeks enter the rolling cooldown window.
    """
    rng = random.Random(seed)

    # Index song pins by date
    song_pins: dict[date, list[str]] = {}
    for pin in pins:
        if pin.songs is not None:
            song_pins[pin.date] = list(pin.songs)

    # Track when each song was last used (including pre-block history)
    song_last_used: dict[str, Optional[date]] = {s.title: s.last_played for s in songs}
    song_map: dict[str, Song] = {s.title: s for s in songs}

    setlists: list[DaySetlist] = []
    cooldown_days = config.song_cooldown_weeks * 7

    for sunday in config.sundays:
        pinned = song_pins.get(sunday, [])

        # Validate pinned songs exist in the library
        for title in pinned:
            if title not in song_map:
                raise ValueError(
                    f"Pinned song '{title}' on {sunday} is not in the song library."
                )

        # Determine eligible songs for the remaining slots
        slots_needed = config.songs_per_setlist - len(pinned)
        eligible = _eligible_songs(songs, sunday, song_last_used, cooldown_days, exclude=set(pinned))

        if len(eligible) < slots_needed:
            raise ValueError(
                f"Not enough eligible songs on {sunday}: need {slots_needed}, "
                f"found {len(eligible)} (after cooldown filtering)."
            )

        chosen = _choose_songs(
            eligible=eligible,
            num_needed=slots_needed,
            target_new=config.target_new_songs_per_setlist - _count_new(pinned, song_map),
            rng=rng,
        )

        setlist_songs = pinned + chosen
        rng.shuffle(setlist_songs)  # randomise song order within the setlist

        setlists.append(DaySetlist(date=sunday, songs=setlist_songs))

        # Update last-used tracking for cooldown purposes
        for title in setlist_songs:
            song_last_used[title] = sunday

    return setlists


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _eligible_songs(
    songs: list[Song],
    on_date: date,
    last_used: dict[str, Optional[date]],
    cooldown_days: int,
    exclude: set[str],
) -> list[Song]:
    """Return songs that are not in cooldown and not already pinned for this date."""
    eligible = []
    for song in songs:
        if song.title in exclude:
            continue
        lu = last_used.get(song.title)
        if lu is not None and (on_date - lu).days < cooldown_days:
            continue
        eligible.append(song)
    return eligible


def _count_new(titles: list[str], song_map: dict[str, Song]) -> int:
    return sum(1 for t in titles if t in song_map and song_map[t].is_new())


def _choose_songs(
    eligible: list[Song],
    num_needed: int,
    target_new: int,
    rng: random.Random,
) -> list[str]:
    """Greedily pick songs targeting a mix of new and established."""
    new_songs = [s for s in eligible if s.is_new()]
    established_songs = [s for s in eligible if not s.is_new()]

    rng.shuffle(new_songs)
    rng.shuffle(established_songs)

    # Clamp target_new to what's available and needed
    target_new = max(0, min(target_new, len(new_songs), num_needed))

    chosen = [s.title for s in new_songs[:target_new]]
    remaining_needed = num_needed - len(chosen)
    chosen += [s.title for s in established_songs[:remaining_needed]]

    # If established songs ran short, fill with remaining new songs
    if len(chosen) < num_needed:
        used = set(chosen)
        for s in new_songs:
            if s.title not in used:
                chosen.append(s.title)
            if len(chosen) == num_needed:
                break

    return chosen

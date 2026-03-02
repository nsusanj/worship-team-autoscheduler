#!/usr/bin/env python3
"""CLI entrypoint for the Worship Team Auto-Scheduler."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scheduler.loader import load_config, load_pins, load_songs, load_volunteers
from scheduler.models import Schedule
from scheduler.output import print_schedule, write_csv
from scheduler.roster import build_roster
from scheduler.setlist import build_setlists


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a worship team schedule (setlists + volunteer roster)."
    )
    parser.add_argument(
        "--config",
        default="data/config.yaml",
        metavar="PATH",
        help="Path to config.yaml (default: data/config.yaml)",
    )
    parser.add_argument(
        "--volunteers",
        default="data/volunteers.yaml",
        metavar="PATH",
        help="Path to volunteers.yaml (default: data/volunteers.yaml)",
    )
    parser.add_argument(
        "--songs",
        default="data/songs.yaml",
        metavar="PATH",
        help="Path to songs.yaml (default: data/songs.yaml)",
    )
    parser.add_argument(
        "--pins",
        default=None,
        metavar="PATH",
        help="Path to pins.yaml (optional)",
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Write CSV output to this file (default: print to stdout)",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "text"],
        default="text",
        help="Output format: 'text' (default) or 'csv'",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible setlist generation",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    print("Loading data...", file=sys.stderr)
    config = load_config(args.config)
    volunteers = load_volunteers(args.volunteers)
    songs = load_songs(args.songs)
    pins = load_pins(args.pins) if args.pins else []

    print(
        f"  {len(volunteers)} volunteers, {len(songs)} songs, "
        f"{config.num_sundays} Sundays, {len(pins)} pins",
        file=sys.stderr,
    )

    # ------------------------------------------------------------------
    # Build setlists
    # ------------------------------------------------------------------
    print("Building setlists...", file=sys.stderr)
    setlists = build_setlists(config, songs, pins, seed=args.seed)

    # ------------------------------------------------------------------
    # Build roster
    # ------------------------------------------------------------------
    print("Building roster...", file=sys.stderr)
    roster = build_roster(config, volunteers, pins)

    # ------------------------------------------------------------------
    # Assemble schedule and output
    # ------------------------------------------------------------------
    schedule = Schedule(setlists=setlists, roster=roster)

    if args.format == "csv" or args.output:
        write_csv(schedule, config, volunteers, args.output)
        if args.output:
            # Also print text summary to stderr
            print_schedule(schedule, config, volunteers)
    else:
        print_schedule(schedule, config, volunteers)


if __name__ == "__main__":
    main()

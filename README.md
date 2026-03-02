# Worship Team Auto-Scheduler

Automatically generates 13-week worship team schedules for multi-location churches. Given a list of volunteers (instruments, skill levels, availability), a song library, and scheduling parameters, it builds weekly setlists and assigns volunteers to each role at each location — optimizing for fair rotation using Google OR-Tools CP-SAT.

## Prerequisites

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip`

## Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd worship-team-autoscheduler

# 2. Create a virtual environment and install dependencies
uv venv
uv pip install -r requirements.txt

# 3. Copy example data files and fill in your real data
cp data/volunteers.example.yaml data/volunteers.yaml
cp data/songs.example.yaml     data/songs.yaml
cp pins.example.yaml           pins.yaml   # optional

# 4. Edit data/config.yaml to match your block dates and locations
```

The real `data/volunteers.yaml`, `data/songs.yaml`, and `pins.yaml` are gitignored to protect volunteer privacy. The `*.example.yaml` files serve as templates.

## Running

```bash
.venv/bin/python schedule.py [OPTIONS]
```

| Flag | Default | Description |
|---|---|---|
| `--config PATH` | `data/config.yaml` | Scheduling parameters |
| `--volunteers PATH` | `data/volunteers.yaml` | Volunteer roster |
| `--songs PATH` | `data/songs.yaml` | Song library |
| `--pins PATH` | *(none)* | Pre-locked assignments (optional) |
| `--output PATH` | *(stdout)* | Write CSV to this file |
| `--format csv\|text` | `text` | Output format |
| `--seed INT` | *(none)* | Random seed for reproducible setlists |

### Examples

```bash
# Print schedule to terminal
.venv/bin/python schedule.py

# Save as CSV
.venv/bin/python schedule.py --output output/schedule_q2.csv --format csv

# Use example data with a fixed seed
.venv/bin/python schedule.py \
  --volunteers data/volunteers.example.yaml \
  --songs data/songs.example.yaml \
  --seed 42

# With pins
.venv/bin/python schedule.py --pins pins.yaml --seed 42
```

## Data Schema

### `data/config.yaml`

```yaml
block_start: "2026-04-06"        # First Sunday (YYYY-MM-DD)
num_sundays: 13                  # Number of weeks to schedule
locations: [Auditorium, Chapel]  # Service locations
roles: [keys, drums, bass, acoustic, electric]  # Instrument roles
vocalists_per_location: 3        # Vocalists scheduled per location per Sunday
song_cooldown_weeks: 6           # Minimum weeks before a song repeats
songs_per_setlist: 3             # Songs per Sunday
target_new_songs_per_setlist: 1  # New songs to introduce per Sunday
auditorium_min_skill: intermediate  # Min skill for Auditorium (beginner | intermediate | advanced)
```

### `data/volunteers.yaml`

```yaml
volunteers:
  - name: "Jane Smith"
    can_play: [keys, acoustic]        # Instruments (empty list if vocalist only)
    preferred_instruments: [keys]     # Optional — subset of can_play; omit or use [] for no preference
    can_sing: true
    skill_level: advanced             # beginner | intermediate | advanced
    target_frequency: 0.62            # Fraction of Sundays desired (0.0–1.0); e.g. 0.62 = ~8 of 13
    blocked_dates:                    # Dates volunteer is unavailable (YYYY-MM-DD)
      - "2026-05-10"
    auditorium_eligible: true         # Can serve at Auditorium (auto-derived from skill if omitted)
```

### `data/songs.yaml`

```yaml
songs:
  - title: "Way Maker"
    status: established          # "established" or "new"
    last_played: "2026-02-09"   # null if never played
```

### `pins.yaml`

Pre-lock volunteer assignments or song choices before the solver runs.

```yaml
pins:
  # Lock a volunteer to a role on a specific date
  - date: "2026-04-06"
    location: Auditorium
    role: keys
    volunteer: "Jane Smith"

  # Lock songs for a Sunday
  - date: "2026-04-06"
    songs: ["Way Maker", "Battle Belongs", "Goodness of God"]
```

## Output

The text output shows a table per Sunday with setlist and volunteer assignments for each location. The CSV output has one row per volunteer-slot for easy import into Google Sheets or Excel.

## Project Structure

```
worship-team-autoscheduler/
├── data/
│   ├── config.yaml                 # Scheduling parameters (committed)
│   ├── volunteers.example.yaml     # Template — copy to volunteers.yaml
│   └── songs.example.yaml          # Template — copy to songs.yaml
├── pins.example.yaml               # Template — copy to pins.yaml
├── output/                         # Generated schedules (gitignored)
├── scheduler/
│   ├── models.py                   # Data models
│   ├── loader.py                   # YAML parsing
│   ├── setlist.py                  # Greedy setlist builder
│   ├── roster.py                   # OR-Tools CP-SAT volunteer solver
│   └── output.py                   # CSV and console output
├── schedule.py                     # CLI entrypoint
└── requirements.txt
```

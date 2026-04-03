# March Madness Bracket Simulator

A probabilistic March Madness bracket simulator that generates thousands of tournament brackets, tracks live NCAA results, and ranks simulated brackets against the actual tournament outcome in real time.

---

## Overview

The idea is simple: instead of filling out one bracket and hoping for the best, this tool generates 10,000 brackets using historical seed win-probability data, then scores every single one against the real tournament as it plays out. You can watch in real time which simulated brackets are surviving the longest, which have gone perfect through a given round, and what the theoretical ceiling is for each bracket still alive.

The project has two main components:
- A **CLI** for initializing the tournament, generating brackets, and entering actual game results round by round
- A **web app** for visualizing the live leaderboard and browsing any individual bracket

---

## How It Works

### 1. Bracket Generation

Brackets are generated probabilistically using historical NCAA tournament data. The simulation uses two models:

**Round 1** uses hardcoded historical seed matchup win rates:
| Matchup | Favorite Win % |
|---------|---------------|
| 1 vs 16 | 99.2% |
| 2 vs 15 | 94.0% |
| 3 vs 14 | 85.0% |
| 5 vs 12 | 65.0% |
| 8 vs 9  | 50.0% |
| ... | ... |

**Rounds 2–6** use a [Bradley-Terry model](https://en.wikipedia.org/wiki/Bradley%E2%80%93Terry_model) with calibrated seed strength values:

```
P(seed A beats seed B) = strength[A] / (strength[A] + strength[B])
```

Seed strengths are tuned so that the implied Round 1 probabilities match historical data. This naturally handles unusual cases like 12-seeds historically outperforming 13-seeds in later rounds.

### 2. Scoring

Brackets are scored using the standard NCAA bracket scoring system:

| Round | Points per correct pick |
|-------|------------------------|
| Round of 64 | 1 |
| Round of 32 | 2 |
| Sweet 16 | 4 |
| Elite 8 | 8 |
| Final Four | 16 |
| Championship | 32 |

The scorer also tracks **potential points** — points still available to a bracket whose picked team hasn't been eliminated yet. This distinguishes between a bracket that is mathematically dead from one that's just behind but still alive.

### 3. Live Tracking

As the real tournament plays out, you enter game results via the CLI (`python main.py update --round N`). The web app recalculates and re-ranks all 10,000 brackets instantly, with no manual refresh needed. Results are cached and only recomputed when the results file changes on disk.

---

## Web Interface

### Leaderboard

The main view ranks all 10,000 brackets by total points. The top 25 are displayed in a table with accuracy percentages, potential points remaining, and a visual accuracy bar.

![Leaderboard](web/static/screenshots/leaderboard.png)

### Current Tournament Bracket

The "Current Bracket" view shows the actual tournament bracket — games that have been played with results, and upcoming matchups derived from completed rounds.

![Current Tournament Bracket](web/static/screenshots/current_bracket.png)

Games are color coded:
- **Green** — result entered / correct pick
- **Gray** — upcoming game (matchup known)
- **Empty** — matchup not yet determined

### Individual Bracket Detail

Click any bracket on the leaderboard to see its full pick-by-pick view. Each game slot is color coded to show whether the pick was correct, wrong, or still pending.

![Bracket Detail](web/static/screenshots/bracket_detail.png)

- **Green** — correct pick
- **Red** — incorrect pick (shows the actual winner in green below)
- **Gray** — game not yet played

The bracket ID, total score, accuracy percentage, and leaderboard rank are shown at the top.

---

## CLI Reference

```
python main.py <command> [options]
```

| Command | Description |
|---------|-------------|
| `init` | Validate `teams.json` and initialize an empty `results.json` |
| `generate --n N` | Generate N simulated brackets (default: 1000) |
| `update --round N` | Interactively enter actual game results for a round |
| `status` | Show how many games have been entered per round |
| `score` | Print the leaderboard to the terminal |
| `perfect` | List all brackets that are still perfect through current play |
| `best-round --round N` | Show brackets with the highest points in a specific round |
| `show --id BRACKET_ID` | Print all picks for a single bracket with resolved team names |

The `update` command walks you through each game in a round, prompting for the winning team by seed or partial name. It detects and skips already-entered games, supports partial round entry, and handles Final Four/Championship pairings correctly.

---

## Data Files

All state lives in the `data/` directory:

```
data/
├── teams.json      # 4 regions × 16 seeds — the starting field
├── brackets.json   # All generated brackets (can be large: ~50MB for 10k brackets)
└── results.json    # Actual tournament results entered round by round
```

**`teams.json`** format:
```json
{
  "South": [
    { "seed": 1, "name": "Auburn" },
    { "seed": 2, "name": "Michigan State" },
    ...
  ],
  "East": [...],
  "West": [...],
  "Midwest": [...]
}
```

---

## Architecture

```
marchmadness/
├── models.py       # Data classes: Team, GameResult, Bracket, BracketScore
├── generator.py    # Probabilistic bracket simulation
├── scorer.py       # Scoring engine and leaderboard computation
├── tournament.py   # Tournament state, file I/O, interactive result entry
└── cli.py          # CLI commands

web/
├── app.py          # FastAPI server with caching
├── templates/
│   ├── index.html      # Leaderboard page
│   └── bracket.html    # Individual bracket page
└── static/
    ├── css/
    │   ├── style.css       # Dark theme base styles
    │   └── bracket.css     # Bracket tree layout and connector lines
    └── js/
        ├── leaderboard.js  # Leaderboard fetch + render
        └── bracket.js      # Bracket fetch + render with game coloring
```

---

## Local Setup

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/)

```bash
# Clone and enter the repo
git clone <repo-url>
cd MarchMadness

# Install dependencies
uv sync

# Add your teams
# Edit data/teams.json with 4 regions × 16 seeds (see format above)

# Initialize the tournament
python main.py init

# Generate 10,000 brackets
python main.py generate --n 10000

# Start the web server
uv run uvicorn web.app:app --reload
# → http://localhost:8000
```

**Entering results as the tournament plays:**

```bash
# After each round completes, enter the results
python main.py update --round 1
python main.py update --round 2
# ... and so on through round 6
```

The web app will automatically pick up result changes and re-rank brackets on the next page load.

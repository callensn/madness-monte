"""
FastAPI web application for the March Madness bracket tracker.

Run with:  uv run uvicorn web.app:app --reload
"""
from __future__ import annotations

import os
import random
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from marchmadness.models import Bracket, BracketScore, GameResult
from marchmadness.scorer import BracketScorer, ROUND_NAMES
from marchmadness.tournament import TournamentState
from marchmadness.generator import REGIONS, FINAL_FOUR_PAIRS

# ---------------------------------------------------------------------------
# Globals loaded at startup
# ---------------------------------------------------------------------------
ALL_BRACKETS: list[Bracket] = []
BRACKET_BY_ID: dict[str, Bracket] = {}
BRACKET_INDEX: dict[str, int] = {}  # bracket_id -> index in list
TEAMS: dict[str, list[dict]] = {}
NAME_LOOKUP: dict[tuple[str, int], str] = {}

WEB_DIR = Path(__file__).parent
DATA_DIR = Path(__file__).parent.parent / "data"

# Score cache: (mtime, scores_list, scorer_instance)
_score_cache: tuple[float, list[BracketScore], BracketScorer] | None = None


def _get_scores() -> tuple[list[BracketScore], BracketScorer, dict[int, list[GameResult]]]:
    """Return cached scores, recomputing only when results.json changes."""
    global _score_cache
    results_path = DATA_DIR / "results.json"
    if not results_path.exists():
        return [], None, {}

    mtime = os.path.getmtime(results_path)
    state = TournamentState(DATA_DIR)
    results = state.load_results()

    if not results:
        return [], None, {}

    if _score_cache is not None and _score_cache[0] == mtime:
        return _score_cache[1], _score_cache[2], results

    scorer = BracketScorer(ALL_BRACKETS, results)
    scores = scorer.score_all()
    _score_cache = (mtime, scores, scorer)
    return scores, scorer, results


def _team_name(region: str, seed: int) -> str:
    return NAME_LOOKUP.get((region, seed), "?")


def _game_status(
    game: GameResult,
    results: dict[int, list[GameResult]],
) -> str:
    """Return 'correct', 'incorrect', or 'pending' for a bracket game."""
    actual_games = results.get(game.round_num)
    if actual_games is None:
        return "pending"

    for actual in actual_games:
        match = False
        if game.round_num <= 4:
            match = (
                actual.game_index == game.game_index
                and actual.region == game.region
            )
        else:
            match = actual.game_index == game.game_index

        if match:
            if (
                game.winning_seed == actual.winning_seed
                and game.winning_region == actual.winning_region
            ):
                return "correct"
            return "incorrect"

    return "pending"


def _game_to_api(game: GameResult, results: dict[int, list[GameResult]]) -> dict:
    """Convert a GameResult to the API response format."""
    status = _game_status(game, results)

    # Find actual winner for incorrect games
    actual_winner = None
    if status == "incorrect":
        actual_games = results.get(game.round_num, [])
        for actual in actual_games:
            match = False
            if game.round_num <= 4:
                match = actual.game_index == game.game_index and actual.region == game.region
            else:
                match = actual.game_index == game.game_index
            if match:
                actual_winner = {
                    "seed": actual.winning_seed,
                    "name": _team_name(actual.winning_region, actual.winning_seed),
                    "region": actual.winning_region,
                }
                break

    return {
        "game_index": game.game_index,
        "home": {
            "seed": game.home_seed,
            "name": _team_name(game.home_region, game.home_seed),
            "region": game.home_region,
        },
        "away": {
            "seed": game.away_seed,
            "name": _team_name(game.away_region, game.away_seed),
            "region": game.away_region,
        },
        "winner": {
            "seed": game.winning_seed,
            "name": _team_name(game.winning_region, game.winning_seed),
            "region": game.winning_region,
        },
        "actual_winner": actual_winner,
        "status": status,
    }


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ALL_BRACKETS, BRACKET_BY_ID, BRACKET_INDEX, TEAMS, NAME_LOOKUP

    print("Loading brackets (this may take 10-15 seconds)...")
    state = TournamentState(DATA_DIR)

    TEAMS = state.load_teams()
    for region, tlist in TEAMS.items():
        for t in tlist:
            NAME_LOOKUP[(region, t["seed"])] = t["name"]

    ALL_BRACKETS = state.load_brackets()
    for idx, b in enumerate(ALL_BRACKETS):
        BRACKET_BY_ID[b.bracket_id] = b
        BRACKET_INDEX[b.bracket_id] = idx

    print(f"Loaded {len(ALL_BRACKETS)} brackets.")
    yield


app = FastAPI(title="March Madness Bracket Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/bracket/current")
async def current_bracket_page(request: Request):
    return templates.TemplateResponse("bracket.html", {"request": request})


@app.get("/bracket/{bracket_id}")
async def bracket_page(request: Request, bracket_id: str):
    if bracket_id not in BRACKET_BY_ID:
        raise HTTPException(404, f"Bracket '{bracket_id}' not found")
    return templates.TemplateResponse("bracket.html", {"request": request})


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

EXPECTED_GAMES: dict[int, int] = {1: 32, 2: 16, 3: 8, 4: 4, 5: 2, 6: 1}


def _round_progress(results: dict[int, list[GameResult]]) -> list[dict]:
    """Return per-round progress info for the API."""
    progress = []
    for rn in range(1, 7):
        entered = len(results.get(rn, []))
        expected = EXPECTED_GAMES[rn]
        progress.append({
            "round": rn,
            "name": ROUND_NAMES[rn],
            "games_entered": entered,
            "games_total": expected,
            "complete": entered >= expected,
        })
    return progress


@app.get("/api/leaderboard")
async def api_leaderboard():
    scores, scorer, results = _get_scores()

    state = TournamentState(DATA_DIR)
    current_round = state.get_current_round() if (DATA_DIR / "results.json").exists() else 0

    if not scores:
        # No results yet — return 25 random brackets
        sample = random.sample(ALL_BRACKETS, min(25, len(ALL_BRACKETS)))
        return {
            "scored": False,
            "current_round": 0,
            "round_name": None,
            "total_brackets": len(ALL_BRACKETS),
            "perfect_count": 0,
            "round_progress": _round_progress({}),
            "brackets": [
                {
                    "rank": None,
                    "bracket_id": b.bracket_id,
                    "total_points": None,
                    "correct_picks": None,
                    "total_scored_games": None,
                    "pct_correct": None,
                    "is_perfect": False,
                }
                for b in sample
            ],
        }

    perfect = scorer.perfect_brackets(scores)
    perfect_ids = {s.bracket_id for s in perfect}
    top_25 = scores[:25]

    # Build round name with progress for partial rounds
    round_name = ROUND_NAMES.get(current_round, f"Round {current_round}")
    if current_round in results:
        entered = len(results[current_round])
        expected = EXPECTED_GAMES.get(current_round, 0)
        if 0 < entered < expected:
            round_name = f"{round_name} ({entered}/{expected})"

    return {
        "scored": True,
        "current_round": current_round,
        "round_name": round_name,
        "total_brackets": len(ALL_BRACKETS),
        "perfect_count": len(perfect),
        "round_progress": _round_progress(results),
        "brackets": [
            {
                "rank": rank,
                "bracket_id": s.bracket_id,
                "total_points": s.total_points,
                "potential_points": s.potential_points,
                "correct_picks": s.correct_picks,
                "total_scored_games": s.total_scored_games,
                "pct_correct": round(s.pct_correct, 4),
                "is_perfect": s.bracket_id in perfect_ids,
            }
            for rank, s in enumerate(top_25, 1)
        ],
    }


@app.get("/api/bracket/current")
async def api_current_bracket():
    """Build the 'master bracket' from actual tournament results."""
    state = TournamentState(DATA_DIR)
    results = state.load_results()

    regions: dict[str, dict[str, list]] = {}
    final_four = []
    championship = []

    # Convert each actual result into the bracket API game format
    for round_num, games in sorted(results.items()):
        for game in games:
            api_game = {
                "game_index": game.game_index,
                "home": {
                    "seed": game.home_seed,
                    "name": _team_name(game.home_region, game.home_seed),
                    "region": game.home_region,
                },
                "away": {
                    "seed": game.away_seed,
                    "name": _team_name(game.away_region, game.away_seed),
                    "region": game.away_region,
                },
                "winner": {
                    "seed": game.winning_seed,
                    "name": _team_name(game.winning_region, game.winning_seed),
                    "region": game.winning_region,
                },
                "actual_winner": None,
                "status": "none",
            }

            if round_num <= 4:
                region = game.region
                regions.setdefault(region, {})
                regions[region].setdefault(str(round_num), [])
                regions[region][str(round_num)].append(api_game)
            elif round_num == 5:
                final_four.append(api_game)
            elif round_num == 6:
                championship.append(api_game)

    # Add upcoming matchups for any round where feeder games are done but
    # the game itself hasn't been played yet. This covers:
    # - Unplayed games in the current partial round (e.g., East S16 when
    #   only West/South S16 are done)
    # - Games in the next round derivable from completed current-round games
    current_round = state.get_current_round()
    teams = state.load_teams()

    # Collect keys of games already added (played results)
    played_keys: set[tuple] = set()
    for rn, games in results.items():
        for g in games:
            played_keys.add((rn, g.game_index, g.region))

    # Check the current round and next round for upcoming matchups
    rounds_to_check = [current_round, current_round + 1] if current_round < 6 else [6]
    for check_round in rounds_to_check:
        if check_round < 1 or check_round > 6:
            continue
        upcoming = state._actual_matchups_for_round(check_round, teams)
        for team_a, team_b, region, game_idx in upcoming:
            if (check_round, game_idx, region) in played_keys:
                continue  # already have actual results for this game

            api_game = {
                "game_index": game_idx,
                "home": {
                    "seed": team_a.seed,
                    "name": team_a.name,
                    "region": team_a.region,
                },
                "away": {
                    "seed": team_b.seed,
                    "name": team_b.name,
                    "region": team_b.region,
                },
                "winner": None,
                "actual_winner": None,
                "status": "upcoming",
            }

            if check_round <= 4:
                regions.setdefault(region, {})
                regions[region].setdefault(str(check_round), [])
                regions[region][str(check_round)].append(api_game)
            elif check_round == 5:
                final_four.append(api_game)
            elif check_round == 6:
                championship.append(api_game)

    # Fill in empty placeholder slots for rounds that have no data yet,
    # so the bracket scaffolding is always fully rendered.
    games_per_region = {1: 8, 2: 4, 3: 2, 4: 1}
    for region in REGIONS:
        regions.setdefault(region, {})
        for rn in range(1, 5):
            rn_str = str(rn)
            existing = regions[region].get(rn_str, [])
            existing_indices = {g["game_index"] for g in existing}
            expected = games_per_region[rn]
            for gi in range(expected):
                if gi not in existing_indices:
                    existing.append({
                        "game_index": gi,
                        "home": None,
                        "away": None,
                        "winner": None,
                        "actual_winner": None,
                        "status": "empty",
                    })
            regions[region][rn_str] = existing

    # Ensure Final Four has 2 slots and Championship has 1 slot
    ff_indices = {g["game_index"] for g in final_four}
    for gi in range(2):
        if gi not in ff_indices:
            final_four.append({
                "game_index": gi,
                "home": None,
                "away": None,
                "winner": None,
                "actual_winner": None,
                "status": "empty",
            })
    champ_indices = {g["game_index"] for g in championship}
    if 0 not in champ_indices:
        championship.append({
            "game_index": 0,
            "home": None,
            "away": None,
            "winner": None,
            "actual_winner": None,
            "status": "empty",
        })

    return {
        "bracket_id": "current",
        "json_index": None,
        "is_current": True,
        "score": None,
        "round_progress": _round_progress(results),
        "regions": regions,
        "final_four": final_four,
        "championship": championship,
    }


@app.get("/api/bracket/{bracket_id}")
async def api_bracket(bracket_id: str):
    bracket = BRACKET_BY_ID.get(bracket_id)
    if bracket is None:
        raise HTTPException(404, f"Bracket '{bracket_id}' not found")

    scores, scorer, results = _get_scores()

    # Compute this bracket's score and rank
    score_data = None
    rank = None
    if scorer:
        bracket_score = scorer.score_bracket(bracket)
        # Find rank
        for i, s in enumerate(scores):
            if s.bracket_id == bracket_id:
                rank = i + 1
                break
        score_data = {
            "total_points": bracket_score.total_points,
            "potential_points": bracket_score.potential_points,
            "correct_picks": bracket_score.correct_picks,
            "total_scored_games": bracket_score.total_scored_games,
            "pct_correct": round(bracket_score.pct_correct, 4),
            "rank": rank,
            "is_perfect": bracket_score.total_scored_games > 0 and bracket_score.pct_correct == 1.0,
            "points_by_round": {str(k): v for k, v in bracket_score.points_by_round.items()},
        }

    # Organize games by region and round
    regions: dict[str, dict[str, list]] = {}
    final_four = []
    championship = []

    for round_num, games in sorted(bracket.rounds.items()):
        for game in games:
            api_game = _game_to_api(game, results)

            if round_num <= 4:
                region = game.region
                regions.setdefault(region, {})
                regions[region].setdefault(str(round_num), [])
                regions[region][str(round_num)].append(api_game)
            elif round_num == 5:
                final_four.append(api_game)
            elif round_num == 6:
                championship.append(api_game)

    return {
        "bracket_id": bracket_id,
        "json_index": BRACKET_INDEX.get(bracket_id),
        "score": score_data,
        "regions": regions,
        "final_four": final_four,
        "championship": championship,
    }

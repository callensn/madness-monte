"""
TournamentState: handles all file I/O and the interactive round-update flow.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Bracket, GameResult, Team
from .generator import ROUND_1_MATCHUPS, FINAL_FOUR_PAIRS, REGIONS

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------

def _game_to_dict(g: GameResult) -> dict:
    return {
        "region": g.region,
        "round_num": g.round_num,
        "game_index": g.game_index,
        "home_seed": g.home_seed,
        "home_region": g.home_region,
        "away_seed": g.away_seed,
        "away_region": g.away_region,
        "winning_seed": g.winning_seed,
        "winning_region": g.winning_region,
    }


def _dict_to_game(d: dict) -> GameResult:
    return GameResult(
        region=d["region"],
        round_num=d["round_num"],
        game_index=d["game_index"],
        home_seed=d["home_seed"],
        home_region=d["home_region"],
        away_seed=d["away_seed"],
        away_region=d["away_region"],
        winning_seed=d["winning_seed"],
        winning_region=d["winning_region"],
    )


def _bracket_to_dict(b: Bracket) -> dict:
    return {
        "bracket_id": b.bracket_id,
        "rounds": {
            str(rn): [_game_to_dict(g) for g in games]
            for rn, games in b.rounds.items()
        },
    }


def _dict_to_bracket(d: dict) -> Bracket:
    rounds = {
        int(rn): [_dict_to_game(g) for g in games]
        for rn, games in d["rounds"].items()
    }
    return Bracket(bracket_id=d["bracket_id"], rounds=rounds)


# ---------------------------------------------------------------------------
# TournamentState
# ---------------------------------------------------------------------------

class TournamentState:
    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.teams_path = data_dir / "teams.json"
        self.brackets_path = data_dir / "brackets.json"
        self.results_path = data_dir / "results.json"

    # --- Teams ---

    def load_teams(self) -> dict[str, list[dict]]:
        with open(self.teams_path) as f:
            return json.load(f)

    def validate_teams(self) -> list[str]:
        """Return a list of error strings (empty = valid)."""
        errors: list[str] = []
        try:
            teams = self.load_teams()
        except FileNotFoundError:
            return [f"teams.json not found at {self.teams_path}"]
        except json.JSONDecodeError as e:
            return [f"teams.json is not valid JSON: {e}"]

        for region in REGIONS:
            if region not in teams:
                errors.append(f"Missing region: {region}")
                continue
            team_list = teams[region]
            if len(team_list) != 16:
                errors.append(f"{region}: expected 16 teams, got {len(team_list)}")
            seeds = {t["seed"] for t in team_list}
            if seeds != set(range(1, 17)):
                errors.append(f"{region}: seeds must be 1-16, got {sorted(seeds)}")
        return errors

    # --- Brackets ---

    def load_brackets(self) -> list[Bracket]:
        with open(self.brackets_path) as f:
            data = json.load(f)
        return [_dict_to_bracket(b) for b in data["brackets"]]

    def save_brackets(self, brackets: list[Bracket]) -> None:
        data = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(brackets),
            "brackets": [_bracket_to_dict(b) for b in brackets],
        }
        with open(self.brackets_path, "w") as f:
            json.dump(data, f)
        print(f"Saved {len(brackets)} brackets to {self.brackets_path}")

    # --- Results ---

    def init_results_file(self) -> None:
        """Create a blank results.json with all rounds set to null."""
        data = {
            "current_round": 0,
            "rounds": {str(r): None for r in range(1, 7)},
        }
        with open(self.results_path, "w") as f:
            json.dump(data, f, indent=2)

    def load_results(self) -> dict[int, list[GameResult]]:
        """Returns only completed (non-null) rounds keyed by round_num."""
        with open(self.results_path) as f:
            data = json.load(f)
        results: dict[int, list[GameResult]] = {}
        for rn_str, games in data["rounds"].items():
            if games is not None:
                results[int(rn_str)] = [_dict_to_game(g) for g in games]
        return results

    def _load_results_raw(self) -> dict:
        with open(self.results_path) as f:
            return json.load(f)

    def save_results(
        self, results: dict[int, list[GameResult]], current_round: int
    ) -> None:
        raw = self._load_results_raw()
        for rn, games in results.items():
            raw["rounds"][str(rn)] = [_game_to_dict(g) for g in games]
        raw["current_round"] = current_round
        with open(self.results_path, "w") as f:
            json.dump(raw, f, indent=2)

    def get_current_round(self) -> int:
        raw = self._load_results_raw()
        return raw.get("current_round", 0)

    # --- Round update (interactive) ---

    def _actual_matchups_for_round(
        self, round_num: int, teams: dict[str, list[dict]]
    ) -> list[tuple[Team, Team, Optional[str], int]]:
        """
        Compute which teams are actually playing in `round_num` by replaying
        all prior actual results.

        Returns list of (team_a, team_b, region_or_None, game_index).
        game_index is per-region for rounds 1-4, matching the generator's scheme.
        """
        # Build seed->Team lookup
        team_lookup: dict[str, dict[int, Team]] = {}
        for region, tlist in teams.items():
            team_lookup[region] = {t["seed"]: Team(t["seed"], t["name"], region) for t in tlist}

        completed = self.load_results()

        if round_num == 1:
            matchups = []
            for region in REGIONS:
                for game_idx, (seed_a, seed_b) in enumerate(ROUND_1_MATCHUPS):
                    matchups.append((
                        team_lookup[region][seed_a],
                        team_lookup[region][seed_b],
                        region,
                        game_idx,
                    ))
            return matchups

        # For rounds 2-4: derive from prior round's actual results within each region.
        # With partial rounds, only include matchups where both feeder games
        # have been completed. game_index values are per-region (0-based).
        if round_num <= 4:
            matchups = []
            for region in REGIONS:
                prev_round_games = [
                    g for g in completed.get(round_num - 1, [])
                    if g.region == region
                ]
                # Index by per-region game_index for pairing lookups
                prev_by_idx = {g.game_index: g for g in prev_round_games}
                games_per_region_prev = {1: 8, 2: 4, 3: 2}[round_num - 1]
                for i in range(0, games_per_region_prev, 2):
                    g_a = prev_by_idx.get(i)
                    g_b = prev_by_idx.get(i + 1)
                    if g_a is not None and g_b is not None:
                        game_idx = i // 2
                        matchups.append((
                            team_lookup[region][g_a.winning_seed],
                            team_lookup[region][g_b.winning_seed],
                            region,
                            game_idx,
                        ))
            return matchups

        if round_num == 5:
            # Final Four: derive Elite 8 winners
            elite8 = completed.get(4, [])
            region_winners: dict[str, Team] = {}
            for g in elite8:
                region_winners[g.winning_region] = team_lookup[g.winning_region][g.winning_seed]
            matchups = []
            for idx, (region_a, region_b) in enumerate(FINAL_FOUR_PAIRS):
                if region_a in region_winners and region_b in region_winners:
                    matchups.append((
                        region_winners[region_a],
                        region_winners[region_b],
                        None,
                        idx,
                    ))
            return matchups

        if round_num == 6:
            # Championship: Final Four winners
            ff = completed.get(5, [])
            ff_winners = [
                team_lookup[g.winning_region][g.winning_seed] for g in ff
            ]
            if len(ff_winners) >= 2:
                return [(ff_winners[0], ff_winners[1], None, 0)]
            return []

        return []

    def _already_entered(
        self, round_num: int, game_index: int, region: Optional[str],
        existing: list[GameResult],
    ) -> Optional[GameResult]:
        """Check if a game has already been entered in results."""
        for g in existing:
            if round_num <= 4:
                if g.game_index == game_index and g.region == region:
                    return g
            else:
                if g.game_index == game_index:
                    return g
        return None

    def _prompt_for_winner(
        self, team_a: Team, team_b: Team, region: Optional[str],
        allow_skip: bool = False,
    ) -> Optional[Team]:
        """
        Interactively prompt the user for a game winner.
        Returns the winning Team, or None if the user skips (when allow_skip=True).
        """
        label_a = f"({team_a.seed}) {team_a.name}"
        label_b = f"({team_b.seed}) {team_b.name}"

        skip_hint = " or 's' to skip" if allow_skip else ""
        if region:
            prompt = f"  {label_a} vs {label_b}  [{team_a.seed}/{team_b.seed}{skip_hint}]: "
        else:
            prompt = (
                f"  {label_a} [{team_a.region}]  vs  "
                f"{label_b} [{team_b.region}]  "
                f"[{team_a.name}/{team_b.name}{skip_hint}]: "
            )

        winner: Optional[Team] = None
        while winner is None:
            raw = input(prompt).strip()
            if allow_skip and raw.lower() in ("s", "skip"):
                return None
            if raw.isdigit():
                seed = int(raw)
                if seed == team_a.seed:
                    winner = team_a
                elif seed == team_b.seed:
                    winner = team_b
                else:
                    print(f"    Invalid seed. Enter {team_a.seed} or {team_b.seed}.")
            else:
                raw_lower = raw.lower()
                if raw_lower in team_a.name.lower():
                    winner = team_a
                elif raw_lower in team_b.name.lower():
                    winner = team_b
                else:
                    print(
                        f"    Not recognized. Enter the seed number "
                        f"({team_a.seed} or {team_b.seed}) or part of a team name."
                    )
        return winner

    def enter_round_results(
        self,
        round_num: int,
        region_filter: Optional[str] = None,
        game_filter: Optional[int] = None,
    ) -> None:
        """
        Interactively prompt for game winners in round_num.

        Already-entered games are skipped (shown as already recorded).
        Use region_filter to enter only one region's games.
        Use game_filter to enter a single game by its index.
        """
        teams = self.load_teams()
        matchups = self._actual_matchups_for_round(round_num, teams)

        if not matchups:
            print(f"Could not determine matchups for round {round_num}. "
                  "Make sure prior rounds are entered.")
            return

        # Load any existing results for this round
        results = self.load_results()
        existing = results.get(round_num, [])

        round_names = {
            1: "Round of 64", 2: "Round of 32", 3: "Sweet 16",
            4: "Elite 8", 5: "Final Four", 6: "Championship",
        }

        # Build filter description for the header
        filter_desc = ""
        if region_filter:
            filter_desc = f" ({region_filter})"
        elif game_filter is not None:
            filter_desc = f" (game {game_filter})"

        print(f"\n{'='*60}")
        print(f"  {round_names.get(round_num, f'Round {round_num}')}{filter_desc} — Enter Results")
        print(f"{'='*60}\n")

        # Build team name lookup for displaying already-entered results
        name_lookup: dict[tuple[str, int], str] = {}
        for r, tlist in teams.items():
            for t in tlist:
                name_lookup[(r, t["seed"])] = t["name"]

        new_games: list[GameResult] = []
        current_region: Optional[str] = None
        skipped = 0
        entered = 0

        for team_a, team_b, region, game_idx in matchups:
            # Apply region filter (rounds 1-4 only)
            if region_filter and region and region != region_filter:
                continue

            # Apply game index filter
            if game_filter is not None and game_idx != game_filter:
                continue

            # Print region header when it changes
            if region != current_region:
                current_region = region
                header = region.upper() if region else "FINAL FOUR / CHAMPIONSHIP"
                print(f"\n--- {header} ---")

            # Check if this game is already entered
            already = self._already_entered(round_num, game_idx, region, existing)
            if already is not None:
                w_name = name_lookup.get((already.winning_region, already.winning_seed), "?")
                w_label = f"({already.winning_seed}) {w_name}"
                label_a = f"({team_a.seed}) {team_a.name}"
                label_b = f"({team_b.seed}) {team_b.name}"
                print(f"  {label_a} vs {label_b}  -> already entered: {w_label}")
                skipped += 1
                continue

            winner = self._prompt_for_winner(team_a, team_b, region, allow_skip=True)

            if winner is None:
                print("    skipped")
                continue

            new_games.append(GameResult(
                region=region,
                round_num=round_num,
                game_index=game_idx,
                home_seed=team_a.seed,
                home_region=team_a.region,
                away_seed=team_b.seed,
                away_region=team_b.region,
                winning_seed=winner.seed,
                winning_region=winner.region,
            ))
            entered += 1

        if not new_games:
            if skipped > 0:
                print(f"\nAll games already entered for this selection ({skipped} games).")
            return

        # Merge new games with existing results for this round
        merged = list(existing) + new_games
        results[round_num] = merged

        # current_round = highest round that has any results
        current_round = max(results.keys())
        self.save_results(results, current_round=current_round)

        total_in_round = len(merged)
        expected = self._expected_games_for_round(round_num)
        status = "complete" if total_in_round >= expected else f"{total_in_round}/{expected}"
        print(f"\nSaved {entered} new game(s). Round {round_num}: {status}.")
        if skipped:
            print(f"  ({skipped} game(s) were already entered.)")

    @staticmethod
    def _expected_games_for_round(round_num: int) -> int:
        """Return the expected number of games for a given round."""
        return {1: 32, 2: 16, 3: 8, 4: 4, 5: 2, 6: 1}.get(round_num, 0)

    def get_round_status(self) -> dict[int, tuple[int, int]]:
        """
        Return {round_num: (games_entered, games_expected)} for all 6 rounds.
        """
        results = self.load_results()
        status: dict[int, tuple[int, int]] = {}
        for rn in range(1, 7):
            expected = self._expected_games_for_round(rn)
            entered = len(results.get(rn, []))
            status[rn] = (entered, expected)
        return status

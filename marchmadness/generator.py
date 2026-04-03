from __future__ import annotations
import random
from typing import Optional

from .models import Team, GameResult, Bracket

# Historical probabilities for Round 1 seed matchups.
# Key: (better_seed, worse_seed), Value: probability that the better seed wins.
ROUND_1_PROBS: dict[tuple[int, int], float] = {
    (1, 16): 0.992,
    (8, 9):  0.500,
    (5, 12): 0.650,
    (4, 13): 0.645,
    (6, 11): 0.625,
    (3, 14): 0.850,
    (7, 10): 0.600,
    (2, 15): 0.938,
}

# Seed strength ratings for rounds 2+ (Bradley-Terry model).
# P(seed A beats seed B) = SEED_STRENGTH[A] / (SEED_STRENGTH[A] + SEED_STRENGTH[B])
# Values calibrated so the implied round-1 probabilities match the historical
# ROUND_1_PROBS above within ~0.5%.  Seeds 12/13 are nearly equal by the data
# (5-over-12 at 65% and 4-over-13 at 64.5% imply similar spreads), so the
# slight non-monotonicity between those two middle seeds is intentional.
SEED_STRENGTH: dict[int, float] = {
    1:  124.0,
    2:   76.0,
    3:   51.0,
    4:   38.0,
    5:   36.0,
    6:   35.0,
    7:   33.0,
    8:   26.0,
    9:   26.0,
    10:  22.0,
    11:  21.0,
    12:  20.0,
    13:  21.0,
    14:   9.0,
    15:   5.0,
    16:   1.0,
}

# Fixed Round 1 matchups: (better_seed, worse_seed) pairs within a region.
ROUND_1_MATCHUPS: list[tuple[int, int]] = [
    (1, 16),
    (8, 9),
    (5, 12),
    (4, 13),
    (6, 11),
    (3, 14),
    (7, 10),
    (2, 15),
]

# Final Four pairings: which two regions play each other.
FINAL_FOUR_PAIRS: list[tuple[str, str]] = [
    ("East", "West"),
    ("South", "Midwest"),
]

REGIONS = ["East", "West", "South", "Midwest"]


class BracketGenerator:
    def __init__(self, teams: dict[str, list[dict]], rng_seed: Optional[int] = None):
        """
        teams: the loaded teams.json structure —
               { "East": [{"seed": 1, "name": "..."}, ...], ... }
        """
        self._rng = random.Random(rng_seed)
        # Build lookup: region -> {seed: Team}
        self._teams: dict[str, dict[int, Team]] = {}
        for region, team_list in teams.items():
            self._teams[region] = {}
            for t in team_list:
                team = Team(seed=t["seed"], name=t["name"], region=region)
                self._teams[region][t["seed"]] = team

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_team(self, region: str, seed: int) -> Team:
        return self._teams[region][seed]

    def _simulate_game(self, a: Team, b: Team, round_num: int) -> Team:
        """Return the winner of a single game."""
        if round_num == 1:
            key = (min(a.seed, b.seed), max(a.seed, b.seed))
            prob_better_seed_wins = ROUND_1_PROBS[key]
            better_team = a if a.seed < b.seed else b
            worse_team  = b if a.seed < b.seed else a
            if self._rng.random() < prob_better_seed_wins:
                return better_team
            return worse_team
        else:
            # Rounds 2+: Bradley-Terry seed strength model
            sa = SEED_STRENGTH[a.seed]
            sb = SEED_STRENGTH[b.seed]
            if self._rng.random() < sa / (sa + sb):
                return a
            return b

    def _simulate_region(self, region: str) -> dict[int, list[GameResult]]:
        """
        Simulate all 4 rounds within a single region (rounds 1-4).
        Returns {round_num: [GameResult, ...]}
        """
        rounds: dict[int, list[GameResult]] = {}

        # Round 1: fixed seed matchups
        r1_games: list[GameResult] = []
        current_winners: list[Team] = []
        for idx, (seed_a, seed_b) in enumerate(ROUND_1_MATCHUPS):
            team_a = self._get_team(region, seed_a)
            team_b = self._get_team(region, seed_b)
            winner = self._simulate_game(team_a, team_b, round_num=1)
            current_winners.append(winner)
            r1_games.append(GameResult(
                region=region,
                round_num=1,
                game_index=idx,
                home_seed=seed_a,
                home_region=region,
                away_seed=seed_b,
                away_region=region,
                winning_seed=winner.seed,
                winning_region=region,
            ))
        rounds[1] = r1_games

        # Rounds 2-4: winner of game 2i plays winner of game 2i+1
        for round_num in range(2, 5):
            next_winners: list[Team] = []
            games: list[GameResult] = []
            num_games = len(current_winners) // 2
            for i in range(num_games):
                team_a = current_winners[2 * i]
                team_b = current_winners[2 * i + 1]
                winner = self._simulate_game(team_a, team_b, round_num=round_num)
                next_winners.append(winner)
                games.append(GameResult(
                    region=region,
                    round_num=round_num,
                    game_index=i,
                    home_seed=team_a.seed,
                    home_region=region,
                    away_seed=team_b.seed,
                    away_region=region,
                    winning_seed=winner.seed,
                    winning_region=region,
                ))
            rounds[round_num] = games
            current_winners = next_winners

        return rounds

    def _simulate_final_four(
        self, region_winners: dict[str, Team]
    ) -> dict[int, list[GameResult]]:
        """
        Simulate rounds 5 (Final Four) and 6 (Championship).
        FINAL_FOUR_PAIRS defines who plays who.
        """
        rounds: dict[int, list[GameResult]] = {5: [], 6: []}
        ff_winners: list[Team] = []

        for idx, (region_a, region_b) in enumerate(FINAL_FOUR_PAIRS):
            team_a = region_winners[region_a]
            team_b = region_winners[region_b]
            winner = self._simulate_game(team_a, team_b, round_num=5)
            ff_winners.append(winner)
            rounds[5].append(GameResult(
                region=None,
                round_num=5,
                game_index=idx,
                home_seed=team_a.seed,
                home_region=region_a,
                away_seed=team_b.seed,
                away_region=region_b,
                winning_seed=winner.seed,
                winning_region=winner.region,
            ))

        # Championship
        champ_winner = self._simulate_game(ff_winners[0], ff_winners[1], round_num=6)
        rounds[6].append(GameResult(
            region=None,
            round_num=6,
            game_index=0,
            home_seed=ff_winners[0].seed,
            home_region=ff_winners[0].region,
            away_seed=ff_winners[1].seed,
            away_region=ff_winners[1].region,
            winning_seed=champ_winner.seed,
            winning_region=champ_winner.region,
        ))

        return rounds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_one(self, bracket_id: str) -> Bracket:
        """Generate a single fully-simulated bracket."""
        all_rounds: dict[int, list[GameResult]] = {}
        region_winners: dict[str, Team] = {}

        for region in REGIONS:
            region_rounds = self._simulate_region(region)
            for round_num, games in region_rounds.items():
                all_rounds.setdefault(round_num, []).extend(games)
            # The Elite 8 winner is the single team remaining after round 4
            region_winners[region] = self._teams[region][
                region_rounds[4][0].winning_seed
            ]

        ff_rounds = self._simulate_final_four(region_winners)
        all_rounds.update(ff_rounds)

        return Bracket(bracket_id=bracket_id, rounds=all_rounds)

    def generate_many(self, n: int = 10000, id_prefix: str = "b") -> list[Bracket]:
        """Generate n brackets with zero-padded IDs like b_00001."""
        width = max(5, len(str(n)))
        brackets = []
        for i in range(1, n + 1):
            bracket_id = f"{id_prefix}_{str(i).zfill(width)}"
            brackets.append(self.generate_one(bracket_id))
        return brackets

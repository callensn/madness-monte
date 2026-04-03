from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Team:
    seed: int
    name: str
    region: str

    def __str__(self) -> str:
        return f"({self.seed}) {self.name}"


@dataclass
class GameResult:
    region: Optional[str]       # None for Final Four / Championship
    round_num: int
    game_index: int             # 0-based within the round
    home_seed: int
    home_region: str
    away_seed: int
    away_region: str
    winning_seed: int
    winning_region: str


@dataclass
class Bracket:
    bracket_id: str
    # round_num (1-6) -> list of GameResult for that round
    rounds: dict[int, list[GameResult]] = field(default_factory=dict)


@dataclass
class BracketScore:
    bracket_id: str
    json_index: int             # 0-based position in brackets.json array
    points_by_round: dict[int, int] = field(default_factory=dict)
    total_points: int = 0
    correct_picks: int = 0
    total_scored_games: int = 0
    potential_points: int = 0

    @property
    def pct_correct(self) -> float:
        if self.total_scored_games == 0:
            return 0.0
        return self.correct_picks / self.total_scored_games

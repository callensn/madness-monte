from __future__ import annotations

from .models import Bracket, BracketScore, GameResult

# Standard NCAA bracket scoring: points double each round.
POINTS_PER_ROUND: dict[int, int] = {
    1: 1,
    2: 2,
    3: 4,
    4: 8,
    5: 16,
    6: 32,
}

ROUND_NAMES: dict[int, str] = {
    1: "Round of 64",
    2: "Round of 32",
    3: "Sweet 16",
    4: "Elite 8",
    5: "Final Four",
    6: "Championship",
}


def _game_key(g: GameResult) -> tuple:
    """Unique key for matching a bracket game to a results game."""
    return (g.round_num, g.game_index, g.region)


class BracketScorer:
    def __init__(
        self,
        brackets: list[Bracket],
        results: dict[int, list[GameResult]],
    ):
        """
        brackets: all generated brackets
        results:  actual tournament results, keyed by round_num.
                  Only includes completed rounds (no None values).
        """
        self.brackets = brackets
        self.results = results
        # Map bracket_id -> 0-based position in the brackets list/JSON array
        self.bracket_index: dict[str, int] = {
            b.bracket_id: idx for idx, b in enumerate(brackets)
        }
        # Pre-compute eliminated teams and scored game keys (shared across all brackets)
        self._eliminated: set[tuple[int, str]] = set()
        self._scored_keys: set[tuple] = set()
        for actual_games in results.values():
            for g in actual_games:
                self._scored_keys.add(_game_key(g))
                # The loser is whichever side is not the winner
                if (g.home_seed, g.home_region) != (g.winning_seed, g.winning_region):
                    self._eliminated.add((g.home_seed, g.home_region))
                if (g.away_seed, g.away_region) != (g.winning_seed, g.winning_region):
                    self._eliminated.add((g.away_seed, g.away_region))

    # ------------------------------------------------------------------
    # Core scoring
    # ------------------------------------------------------------------

    def score_bracket(self, bracket: Bracket) -> BracketScore:
        """Score a single bracket against all completed rounds."""
        score = BracketScore(
            bracket_id=bracket.bracket_id,
            json_index=self.bracket_index[bracket.bracket_id],
        )

        for round_num, actual_games in self.results.items():
            predicted_games = bracket.rounds.get(round_num, [])
            # Index predicted games by (round_num, game_index) for O(1) lookup
            predicted_by_key = {
                _game_key(g): g for g in predicted_games
            }
            pts = 0
            correct = 0
            for actual in actual_games:
                key = _game_key(actual)
                predicted = predicted_by_key.get(key)
                if predicted is not None:
                    if (
                        predicted.winning_seed == actual.winning_seed
                        and predicted.winning_region == actual.winning_region
                    ):
                        pts += POINTS_PER_ROUND[round_num]
                        correct += 1
                score.total_scored_games += 1

            score.points_by_round[round_num] = pts
            score.total_points += pts
            score.correct_picks += correct

        # Potential points: earned points + points from unscored games
        # where the predicted winner hasn't been eliminated
        potential = score.total_points
        for round_num, predicted_games in bracket.rounds.items():
            for g in predicted_games:
                if _game_key(g) not in self._scored_keys:
                    if (g.winning_seed, g.winning_region) not in self._eliminated:
                        potential += POINTS_PER_ROUND[round_num]
        score.potential_points = potential

        return score

    def score_all(self) -> list[BracketScore]:
        """Score every bracket. Returns list sorted by total_points descending."""
        scores = [self.score_bracket(b) for b in self.brackets]
        scores.sort(key=lambda s: (s.total_points, s.potential_points), reverse=True)
        return scores

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    def perfect_brackets(self, scores: list[BracketScore]) -> list[BracketScore]:
        """Return all brackets with 100% accuracy through scored rounds."""
        return [s for s in scores if s.total_scored_games > 0 and s.pct_correct == 1.0]

    def best_per_round(
        self, scores: list[BracketScore]
    ) -> dict[int, list[BracketScore]]:
        """
        For each scored round, return the bracket(s) that earned the most
        points specifically in that round.
        """
        completed_rounds = set(self.results.keys())
        result: dict[int, list[BracketScore]] = {}
        for round_num in sorted(completed_rounds):
            best_pts = max(
                (s.points_by_round.get(round_num, 0) for s in scores), default=0
            )
            result[round_num] = [
                s for s in scores
                if s.points_by_round.get(round_num, 0) == best_pts
            ]
        return result

    def top_brackets(
        self, scores: list[BracketScore], n: int = 10
    ) -> list[tuple[BracketScore, int]]:
        """
        Return the top-n brackets as (BracketScore, json_index) tuples.
        Scores must already be sorted descending (e.g. from score_all()).
        """
        return [(s, s.json_index) for s in scores[:n]]

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def leaderboard(self, scores: list[BracketScore], top_n: int = 20) -> str:
        """Format a leaderboard string for the top_n brackets."""
        lines: list[str] = []

        # --- Perfect brackets section ---
        perfect = self.perfect_brackets(scores)
        if perfect:
            lines.append(f"{'='*62}")
            lines.append(f"  PERFECT BRACKETS ({len(perfect)} found!)")
            lines.append(f"{'='*62}")
            for s in perfect:
                lines.append(
                    f"  {s.bracket_id}  (JSON index {s.json_index})  "
                    f"{s.correct_picks}/{s.total_scored_games} correct  "
                    f"{s.total_points} pts"
                )
            lines.append("")

        # --- Main leaderboard ---
        completed_rounds = sorted(self.results.keys())
        scored_through = (
            f"through {ROUND_NAMES[max(completed_rounds)]}"
            if completed_rounds
            else "no rounds scored yet"
        )
        lines.append(f"{'='*62}")
        lines.append(f"  LEADERBOARD  ({scored_through})")
        lines.append(f"{'='*62}")

        col_w = [5, 12, 10, 7, 10, 9, 7]  # Rank, ID, JSON idx, Pts, Potential, Correct, Pct
        header = (
            f"{'Rank':<{col_w[0]}} "
            f"{'Bracket':<{col_w[1]}} "
            f"{'JSON Idx':<{col_w[2]}} "
            f"{'Points':>{col_w[3]}} "
            f"{'Potential':>{col_w[4]}} "
            f"{'Correct':>{col_w[5]}} "
            f"{'Pct':>{col_w[6]}}"
        )
        lines.append(header)
        lines.append("-" * 72)

        for rank, s in enumerate(scores[:top_n], start=1):
            pct = f"{s.pct_correct * 100:.1f}%"
            lines.append(
                f"{rank:<{col_w[0]}} "
                f"{s.bracket_id:<{col_w[1]}} "
                f"{s.json_index:<{col_w[2]}} "
                f"{s.total_points:>{col_w[3]}} "
                f"{s.potential_points:>{col_w[4]}} "
                f"{s.correct_picks:>{col_w[5]}} "
                f"{pct:>{col_w[6]}}"
            )

        return "\n".join(lines)

    def format_best_per_round(self, scores: list[BracketScore]) -> str:
        """Format the best-per-round analysis as a string."""
        bpr = self.best_per_round(scores)
        lines: list[str] = [f"{'='*62}", "  BEST BRACKET PER ROUND", f"{'='*62}"]
        for round_num, top in bpr.items():
            pts = top[0].points_by_round.get(round_num, 0)
            ids = ", ".join(
                f"{s.bracket_id} (idx {s.json_index})" for s in top[:5]
            )
            suffix = f" (+{len(top)-5} more)" if len(top) > 5 else ""
            lines.append(
                f"  {ROUND_NAMES[round_num]:<18}  {pts} pts  →  {ids}{suffix}"
            )
        return "\n".join(lines)

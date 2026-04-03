"""
CLI entry point — all subcommands for the March Madness bracket system.

Usage:
  python main.py init
  python main.py generate [--n 10000] [--seed N]
  python main.py update --round N
  python main.py score [--top N]
  python main.py perfect
  python main.py best-round --round N [--top K]
  python main.py show --id BRACKET_ID
"""
from __future__ import annotations

import argparse
import sys

from .tournament import TournamentState
from .generator import BracketGenerator
from .scorer import BracketScorer, ROUND_NAMES


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> None:
    state = TournamentState()

    errors = state.validate_teams()
    if errors:
        print("teams.json validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    teams = state.load_teams()
    total = sum(len(v) for v in teams.values())
    print(f"teams.json OK — {total} teams across {len(teams)} regions.")

    state.init_results_file()
    print(f"results.json initialized at {state.results_path}")
    print("\nReady. Next step: python main.py generate --n 10000")


def cmd_generate(args: argparse.Namespace) -> None:
    state = TournamentState()

    errors = state.validate_teams()
    if errors:
        print("teams.json is invalid — run `python main.py init` first.")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    teams = state.load_teams()
    n = args.n
    rng_seed = args.seed

    seed_msg = f" (RNG seed={rng_seed})" if rng_seed is not None else ""
    print(f"Generating {n} brackets{seed_msg}...")

    gen = BracketGenerator(teams, rng_seed=rng_seed)
    brackets = gen.generate_many(n=n)

    state.save_brackets(brackets)
    print(f"Done. {n} brackets saved to {state.brackets_path}")
    print("\nNext step: python main.py update --round 1  (after Round 1 completes)")


def cmd_update(args: argparse.Namespace) -> None:
    state = TournamentState()

    if not state.results_path.exists():
        print("results.json not found. Run `python main.py init` first.")
        sys.exit(1)

    state.enter_round_results(
        args.round,
        region_filter=args.region,
        game_filter=args.game,
    )
    print(f"\nNext step: python main.py score  (to see standings)")


def cmd_status(args: argparse.Namespace) -> None:
    state = TournamentState()

    if not state.results_path.exists():
        print("results.json not found. Run `python main.py init` first.")
        sys.exit(1)

    status = state.get_round_status()

    print(f"\n{'='*50}")
    print(f"  TOURNAMENT STATUS")
    print(f"{'='*50}")

    for rn in range(1, 7):
        entered, expected = status[rn]
        name = ROUND_NAMES.get(rn, f"Round {rn}")
        if entered == 0:
            state_str = "pending"
        elif entered >= expected:
            state_str = "COMPLETE"
        else:
            state_str = f"in progress ({entered}/{expected})"
        print(f"  {name:<18}  {state_str}")

    print()


def cmd_score(args: argparse.Namespace) -> None:
    state = TournamentState()

    if not state.brackets_path.exists():
        print("No brackets found. Run `python main.py generate` first.")
        sys.exit(1)
    if not state.results_path.exists():
        print("No results found. Run `python main.py init` and then `update --round N`.")
        sys.exit(1)

    brackets = state.load_brackets()
    results = state.load_results()

    if not results:
        print("No rounds have been scored yet. Enter results with `python main.py update --round 1`.")
        return

    scorer = BracketScorer(brackets, results)
    scores = scorer.score_all()
    print(scorer.leaderboard(scores, top_n=args.top))


def cmd_perfect(args: argparse.Namespace) -> None:
    state = TournamentState()

    if not state.brackets_path.exists():
        print("No brackets found. Run `python main.py generate` first.")
        sys.exit(1)

    brackets = state.load_brackets()
    results = state.load_results()

    if not results:
        print("No rounds scored yet.")
        return

    scorer = BracketScorer(brackets, results)
    scores = scorer.score_all()
    perfect = scorer.perfect_brackets(scores)

    completed = sorted(results.keys())
    scored_through = ROUND_NAMES[max(completed)] if completed else "?"

    print(f"\n{'='*60}")
    print(f"  PERFECT BRACKETS through {scored_through}")
    print(f"{'='*60}")

    if not perfect:
        print("  None — no bracket has been 100% correct so far.")
    else:
        print(f"  {len(perfect)} bracket(s) still perfect:\n")
        for s in perfect:
            pts_detail = "  ".join(
                f"R{r}:{p}pts" for r, p in sorted(s.points_by_round.items())
            )
            print(
                f"  {s.bracket_id}  (JSON index {s.json_index})"
                f"  {s.correct_picks}/{s.total_scored_games} correct"
                f"  {s.total_points} pts"
            )
            print(f"    breakdown: {pts_detail}")


def cmd_best_round(args: argparse.Namespace) -> None:
    state = TournamentState()

    if not state.brackets_path.exists():
        print("No brackets found. Run `python main.py generate` first.")
        sys.exit(1)

    brackets = state.load_brackets()
    results = state.load_results()

    if not results:
        print("No rounds scored yet.")
        return

    scorer = BracketScorer(brackets, results)
    scores = scorer.score_all()

    if args.round is not None:
        # Single round report
        round_num = args.round
        if round_num not in results:
            print(f"Round {round_num} has not been entered yet.")
            return
        bpr = scorer.best_per_round(scores)
        top = bpr.get(round_num, [])
        pts = top[0].points_by_round.get(round_num, 0) if top else 0
        top_k = top[:args.top]
        print(f"\n{'='*60}")
        print(f"  Best in {ROUND_NAMES[round_num]} — {pts} pts")
        print(f"{'='*60}")
        for rank, s in enumerate(top_k, 1):
            print(f"  {rank}. {s.bracket_id}  (JSON index {s.json_index})  "
                  f"{s.points_by_round.get(round_num, 0)} pts this round  "
                  f"{s.total_points} pts total")
        if len(top) > args.top:
            print(f"  ... and {len(top) - args.top} more with the same score.")
    else:
        # All rounds
        print(scorer.format_best_per_round(scores))


def cmd_show(args: argparse.Namespace) -> None:
    state = TournamentState()

    if not state.brackets_path.exists():
        print("No brackets found. Run `python main.py generate` first.")
        sys.exit(1)

    brackets = state.load_brackets()

    target = next((b for b in brackets if b.bracket_id == args.id), None)
    if target is None:
        print(f"Bracket '{args.id}' not found.")
        sys.exit(1)

    # Find index
    idx = next(i for i, b in enumerate(brackets) if b.bracket_id == args.id)

    # Load teams for name resolution
    teams_raw = state.load_teams()
    name_lookup: dict[tuple[str, int], str] = {}
    for region, tlist in teams_raw.items():
        for t in tlist:
            name_lookup[(region, t["seed"])] = t["name"]

    def team_str(seed: int, region: str) -> str:
        name = name_lookup.get((region, seed), "?")
        return f"({seed}) {name}"

    print(f"\n{'='*60}")
    print(f"  BRACKET: {target.bracket_id}  (JSON index {idx})")
    print(f"{'='*60}")

    for round_num in sorted(target.rounds.keys()):
        games = target.rounds[round_num]
        print(f"\n  --- {ROUND_NAMES.get(round_num, f'Round {round_num}')} ---")
        for g in games:
            home = team_str(g.home_seed, g.home_region)
            away = team_str(g.away_seed, g.away_region)
            winner = team_str(g.winning_seed, g.winning_region)
            region_tag = f"[{g.region}] " if g.region else ""
            print(f"    {region_tag}{home} vs {away}  →  {winner}")

    # Show score if results are available
    if state.results_path.exists():
        results = state.load_results()
        if results:
            scorer = BracketScorer(brackets, results)
            score = scorer.score_bracket(target)
            print(f"\n  Points: {score.total_points}  |  "
                  f"Correct: {score.correct_picks}/{score.total_scored_games}  |  "
                  f"Accuracy: {score.pct_correct * 100:.1f}%")
            breakdown = "  ".join(
                f"R{r}:{p}pts" for r, p in sorted(score.points_by_round.items())
            )
            print(f"  Breakdown: {breakdown}")


# ---------------------------------------------------------------------------
# Parser setup
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marchmadness",
        description="March Madness bracket simulator and scorer.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = sub.add_parser("init", help="Validate teams.json and create results.json")
    p_init.set_defaults(func=cmd_init)

    # generate
    p_gen = sub.add_parser("generate", help="Generate N random brackets")
    p_gen.add_argument("--n", type=int, default=10000, metavar="N",
                       help="Number of brackets to generate (default: 10000)")
    p_gen.add_argument("--seed", type=int, default=None, metavar="SEED",
                       help="Optional RNG seed for reproducibility")
    p_gen.set_defaults(func=cmd_generate)

    # update
    p_upd = sub.add_parser("update", help="Enter actual results for a round")
    p_upd.add_argument("--round", type=int, required=True, metavar="N",
                       choices=range(1, 7), help="Round number (1-6)")
    p_upd.add_argument("--region", type=str, default=None,
                       choices=["East", "West", "South", "Midwest"],
                       help="Only enter results for this region")
    p_upd.add_argument("--game", type=int, default=None, metavar="IDX",
                       help="Only enter result for this game index")
    p_upd.set_defaults(func=cmd_update)

    # status
    p_status = sub.add_parser("status", help="Show tournament progress")
    p_status.set_defaults(func=cmd_status)

    # score
    p_score = sub.add_parser("score", help="Print leaderboard")
    p_score.add_argument("--top", type=int, default=20, metavar="N",
                         help="Number of brackets to show (default: 20)")
    p_score.set_defaults(func=cmd_score)

    # perfect
    p_perf = sub.add_parser("perfect", help="List all 100%% accurate brackets")
    p_perf.set_defaults(func=cmd_perfect)

    # best-round
    p_br = sub.add_parser("best-round", help="Show the top bracket(s) for a specific round")
    p_br.add_argument("--round", type=int, default=None, metavar="N",
                      choices=range(1, 7),
                      help="Round to inspect (omit for all rounds)")
    p_br.add_argument("--top", type=int, default=5, metavar="K",
                      help="How many to show (default: 5)")
    p_br.set_defaults(func=cmd_best_round)

    # show
    p_show = sub.add_parser("show", help="Display all picks for a single bracket")
    p_show.add_argument("--id", required=True, metavar="BRACKET_ID",
                        help="Bracket ID to display (e.g. b_00042)")
    p_show.set_defaults(func=cmd_show)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)

"""datadraft CLI (Milestone 1).

  datadraft leagues <sleeper_username> [--season 2026]
  datadraft trade <league_id> "A, B for C" [--no-court] [--band 1.0]

"A, B for C" means you send A and B and receive C. Your team is whichever roster holds
A and B, so the same command works for anyone in the league."""

from __future__ import annotations

import argparse
import sys

from .decide import BAND
from .delta import TradeDelta, player_name
from .engine import evaluate
from .ingest import FetchError, PayloadStore, SleeperClient, data_dir
from .snapshot import build_snapshot


def team_name(snap, roster_id: int) -> str:
    owner = next((r.get("owner_id") for r in snap.rosters if int(r["roster_id"]) == roster_id),
                 None)
    user = next((u for u in snap.users if u.get("user_id") == owner), {})
    return (user.get("metadata") or {}).get("team_name") or user.get("display_name") \
        or f"Roster {roster_id}"


def _names(snap, pids) -> str:
    return ", ".join(player_name(snap.players, p) for p in pids)


def _signed(x: float) -> str:
    return f"{x:+.1f}"


def copy_dm(snap, c: TradeDelta) -> str:
    """§4: a template over the counteroffer's numbers, not LLM prose."""
    return (f"Would you do {_names(snap, c.trade.give)} for {_names(snap, c.trade.get)}? "
            f"By my projections it's about {_signed(c.them.delta)} pts/wk for your lineup "
            f"through the playoffs.")


def _delta_table(snap, d: TradeDelta) -> list[str]:
    them = team_name(snap, d.trade.them)
    lines = ["| | You | " + them + " |", "|---|---:|---:|",
             f"| Lineup change, pts/week | **{_signed(d.me.delta)}** | {_signed(d.them.delta)} |"]
    for w in d.weeks:
        lines.append(f"| Week {w} | {_signed(d.me.per_week[w])} | {_signed(d.them.per_week[w])} |")
    for who, side in (("You", d.me), (them, d.them)):
        if side.forced_drops:
            lines.append(f"\nForced drop ({who}, roster limit): {_names(snap, side.forced_drops)}")
    return lines


def render(result) -> str:
    snap, r = result.snapshot, result.ruling
    out = []
    if result.error:
        return f"# Trade Court: paused\n\n{result.error}\n"
    out.append(f"# Trade Court: {r.verdict}\n")
    if r.reason:
        out.append(f"{r.reason}\n")
    meta = (f"Snapshot `{snap.snapshot_id}` · projections as of {snap.build_as_of} · "
            f"rosters as of {snap.league_as_of}")
    if r.delta is None:
        out.append(meta)
        return "\n".join(out) + "\n"
    d = r.delta
    out.append(f"**You send:** {_names(snap, d.trade.give)}  \n"
               f"**You get:** {_names(snap, d.trade.get)} (from {team_name(snap, d.trade.them)})  \n"
               f"Weeks {d.weeks[0]}-{d.weeks[-1]} · band ±{r.band:.1f} pts/week  \n{meta}\n")
    out.append("## The numbers\n")
    out += _delta_table(snap, d)
    out.append(f"\nThey'd likely say {'yes' if d.them.delta > 0 else 'no'}.")
    if r.counter:
        c = r.counter
        out.append("\n## Counteroffer\n")
        out.append(f"**Send:** {_names(snap, c.trade.give)}  \n**Ask for:** {_names(snap, c.trade.get)}\n")
        out += _delta_table(snap, c)
        out.append(f"\n**Copy DM:** {copy_dm(snap, c)}")
    ct = result.court
    if ct:
        for section, title in (("for", "For"), ("against", "Against"), ("rationale", "Why")):
            args = ct.arguments.get(section) or []
            if args:
                out.append(f"\n## {title}\n")
                out += [f"- {a.text} `{' '.join(a.evidence_ids)}`" for a in args]
        if ct.notice:
            out.append(f"\n> {ct.notice}")
    for n in r.notes:
        out.append(f"\n> {n}")
    if result.ledger_key:
        out.append(f"\nFrozen in the ledger as `{result.ledger_key}`.")
    return "\n".join(out) + "\n"


def cmd_leagues(args) -> int:
    client = SleeperClient(PayloadStore(data_dir()))
    user = client.user(args.username).data
    if not user:
        print(f"No Sleeper user named {args.username!r}.", file=sys.stderr)
        return 1
    season = args.season or str(client.state().data.get("season"))
    leagues = client.leagues(user["user_id"], season).data or []
    if not leagues:
        print(f"{args.username} has no {season} NFL leagues.")
    for lg in leagues:
        print(f"{lg['league_id']}  {lg.get('name', '')}  ({lg.get('total_rosters')} teams)")
    return 0


def cmd_trade(args) -> int:
    client = SleeperClient(PayloadStore(data_dir()))
    try:
        snap = build_snapshot(client, args.league_id)
    except FetchError as e:
        print(f"Can't reach Sleeper right now: {e}. Try again shortly.", file=sys.stderr)
        return 2
    if not snap.league:
        print(f"No Sleeper league with id {args.league_id}.", file=sys.stderr)
        return 1
    result = evaluate({"type": "trade", "text": args.trade}, snap.snapshot_id, snapshot=snap,
                      band=args.band, use_court=not args.no_court)
    print(render(result))
    return 3 if result.error else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="datadraft", description="NFL fantasy trade rulings "
                                "for Sleeper leagues.")
    sub = p.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("leagues", help="list a Sleeper user's leagues and their ids")
    lg.add_argument("username")
    lg.add_argument("--season")
    lg.set_defaults(func=cmd_leagues)
    tr = sub.add_parser("trade", help="rule on a trade: 'A, B for C' (you send A, B)")
    tr.add_argument("league_id")
    tr.add_argument("trade")
    tr.add_argument("--no-court", action="store_true", help="skip the Claude arguments")
    tr.add_argument("--band", type=float, default=BAND, help="verdict band, pts/week")
    tr.set_defaults(func=cmd_trade)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

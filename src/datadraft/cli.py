"""datadraft CLI (Milestone 1).

  datadraft leagues <sleeper_username> [--season 2026]
  datadraft trade <league_id> "A, B for C" [--no-court] [--band 1.0]
  datadraft waivers <league_id> --team <username or roster number>
  datadraft startsit <league_id> --team <username or roster number>

With DATABASE_URL set (Milestone 2), rulings sit on the daily build in Postgres:
  datadraft db init                      create the tables
  datadraft pipeline [--league ID ...]   run the daily build (default: DATADRAFT_LEAGUES)
  datadraft status                       show the current build
  datadraft compare <league_id> [--weeks 6-8]   backtest Sleeper vs the baseline

"A, B for C" means you send A and B and receive C. Your team is whichever roster holds
A and B, so the same command works for anyone in the league."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from . import db

from .decide import BAND
from .delta import TradeDelta, player_name
from .engine import evaluate
from .ingest import FetchError, PayloadStore, SleeperClient, data_dir
from .snapshot import NoBuild, build_snapshot


def make_client() -> SleeperClient:
    return SleeperClient(db.PgPayloadStore() if db.enabled() else PayloadStore(data_dir()))


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


def _chip(c) -> str:
    bits = [c.source] + ([c.availability] if c.availability else []) + \
        (["approx. scoring"] if getattr(c, "approx", False) else [])
    return "`" + " · ".join(b for b in bits if b) + "`"


def find_roster(snap, client, team: str) -> int | None:
    """A roster number, a Sleeper username/display name, or a team name."""
    if team.isdigit() and any(int(r["roster_id"]) == int(team) for r in snap.rosters):
        return int(team)
    key = team.strip().lower()
    uid = next((u["user_id"] for u in snap.users
                if key in {str(u.get("display_name", "")).lower(),
                           str((u.get("metadata") or {}).get("team_name", "")).lower()}), None)
    if uid is None:
        try:
            uid = (client.user(team).data or {}).get("user_id")
        except FetchError:
            uid = None
    for r in snap.rosters:
        if uid and (r.get("owner_id") == uid or uid in (r.get("co_owners") or [])):
            return int(r["roster_id"])
    return None


def render_waivers(result) -> str:
    snap, w = result.snapshot, result.waivers
    if result.error:
        return f"# Waivers: unavailable\n\n{result.error}\n"
    me = team_name(snap, w.roster_id)
    out = [f"# Waivers: {me}\n",
           f"Weeks {w.weeks[0]}-{w.weeks[-1]} · {w.considered} free agents beat someone on "
           f"your roster at their position · projections as of {snap.build_as_of} · "
           f"rosters as of {snap.league_as_of}\n"]
    if not w.picks:
        out.append(f"No free agent beats your bench right now (checked {snap.league_as_of}).")
    else:
        out += ["| Add | Drop | Lineup change, pts/week | Status |", "|---|---|---:|---|"]
        for p in w.picks:
            drop = player_name(snap.players, p.drop) if p.drop else "(open roster spot)"
            status = "Waivers: best add if you win the claim" if p.status == "waivers" \
                else "Free agent"
            out.append(f"| {player_name(snap.players, p.add)} | {drop} | "
                       f"**{_signed(p.delta)}** | {status} |")
        top = w.picks[0]
        out.append(f"\nTop pick, by week: " + ", ".join(
            f"wk {wk} {_signed(v)}" for wk, v in top.side.per_week.items()))
    for n in result.notes:
        out.append(f"\n> {n}")
    return "\n".join(out) + "\n"


def render_startsit(result) -> str:
    snap, s = result.snapshot, result.startsit
    if result.error:
        return f"# Start/Sit: unavailable\n\n{result.error}\n"
    out = [f"# Start/Sit: {team_name(snap, s.roster_id)}, week {s.week}\n",
           "| Slot | Player | Pts | Evidence |", "|---|---|---:|---|"]
    for p in s.slots:
        if not p.player_id:
            out.append(f"| {p.slot} | (empty) | 0.0 | |")
            continue
        name = player_name(snap.players, p.player_id)
        if p.locked:
            out.append(f"| {p.slot} | {name} LOCKED | {p.points:.1f} | `actual · {s.live_as_of}` |")
        else:
            c = result.matrix.get(s.week, {}).get(p.player_id)
            out.append(f"| {p.slot} | {name} | {p.points:.1f} | {_chip(c) if c else ''} |")
    if s.start or s.sit:
        out.append(f"\n**Start** {_names(snap, s.start) or '(nobody)'}; **sit** "
                   f"{_names(snap, s.sit) or '(nobody)'}: {_signed(s.gain)} projected pts.")
    else:
        out.append("\nYour current lineup is already the best one.")
    out.append(f"\nProjected total {s.total:.1f} (locked players at actual points). "
               f"Statuses as of {snap.build_as_of}; live scores as of {s.live_as_of}.")
    for wmsg in s.warnings + result.notes:
        out.append(f"\n> {wmsg}")
    return "\n".join(out) + "\n"


def _roster_cmd(args, kind: str) -> int:
    import time as _time

    client = make_client()
    try:
        snap = build_snapshot(client, args.league_id)
    except FetchError as e:
        print(f"Can't reach Sleeper right now: {e}. Try again shortly.", file=sys.stderr)
        return 2
    except NoBuild as e:
        print(f"No projections to work from: {e}.", file=sys.stderr)
        return 2
    if not snap.league:
        print(f"No Sleeper league with id {args.league_id}.", file=sys.stderr)
        return 1
    rid = find_roster(snap, client, args.team)
    if rid is None:
        teams = ", ".join(f"{r['roster_id']} {team_name(snap, int(r['roster_id']))}"
                          for r in snap.rosters)
        print(f"No team matches {args.team!r}. Rosters: {teams}", file=sys.stderr)
        return 1
    action = {"type": kind, "roster_id": rid}
    if kind == "startsit":
        live = client.matchups(args.league_id, snap.current_week)
        action |= {"live": next((m for m in live.data or [] if int(m["roster_id"]) == rid), {}),
                   "live_as_of": dt.datetime.fromtimestamp(live.fetched_at, dt.UTC)
                   .strftime("%Y-%m-%dT%H:%MZ"), "now": _time.time()}
    result = evaluate(action, snap.snapshot_id, snapshot=snap)
    print(render_waivers(result) if kind == "waiver" else render_startsit(result))
    return 3 if result.error else 0


def cmd_waivers(args) -> int:
    return _roster_cmd(args, "waiver")


def cmd_startsit(args) -> int:
    return _roster_cmd(args, "startsit")


def cmd_leagues(args) -> int:
    client = make_client()
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
    client = make_client()
    try:
        snap = build_snapshot(client, args.league_id)
    except FetchError as e:
        print(f"Can't reach Sleeper right now: {e}. Try again shortly.", file=sys.stderr)
        return 2
    except NoBuild as e:
        print(f"No projections to rule on: {e}.", file=sys.stderr)
        return 2
    if not snap.league:
        print(f"No Sleeper league with id {args.league_id}.", file=sys.stderr)
        return 1
    result = evaluate({"type": "trade", "text": args.trade}, snap.snapshot_id, snapshot=snap,
                      band=args.band, use_court=not args.no_court)
    print(render(result))
    return 3 if result.error else 0


def _need_db() -> bool:
    if not db.enabled():
        print("Set DATABASE_URL first (docker compose up -d, then see README).", file=sys.stderr)
        return False
    return True


def cmd_db(args) -> int:
    if not _need_db():
        return 1
    db.init()
    print("Tables are ready.")
    return 0


def cmd_pipeline(args) -> int:
    from .pipeline import BuildError, run_daily

    if not _need_db():
        return 1
    leagues = args.league or [x for x in os.environ.get("DATADRAFT_LEAGUES", "").split(",") if x]
    db.init()
    try:
        rep = run_daily(db.conn(), make_client(), leagues)
    except (BuildError, FetchError) as e:
        print(f"Build not published, the previous one stays current: {e}", file=sys.stderr)
        return 2
    print(f"Published build {rep.build_id} (weeks {rep.weeks[0]}-{rep.weeks[-1]})")
    print(f"  players {rep.counts['players']}, projection rows {rep.counts['projection_rows']}, "
          f"stats {rep.counts['projection_stats']}")
    print("  nflverse " + ", ".join(f"{k} {v}" for k, v in rep.counts["nflverse"].items()))
    print(f"  rostered players with no nflverse match: {len(rep.unmatched)}")
    for lid, g in rep.guard.items():
        print(f"  guard {lid}: {g}")
    print("  pruned " + ", ".join(f"{k} {v}" for k, v in rep.pruned.items()))
    return 0


def cmd_status(args) -> int:
    if not _need_db():
        return 1
    row = db.conn().execute(
        "select b.build_id, b.as_of, b.weeks, b.guard, b.counts, c.flipped_at, "
        "(select count(*) from builds), (select count(*) from ledger) "
        "from current_build c join builds b using (build_id)").fetchone()
    if row is None:
        print("No build published yet. Run `datadraft pipeline --league <league_id>`.")
        return 1
    bid, as_of, weeks, guard, counts, flipped, n_builds, n_ledger = row
    age_h = (dt.datetime.now(dt.UTC).timestamp() - as_of) / 3600
    print(f"Current build {bid}, data as of "
          f"{dt.datetime.fromtimestamp(as_of, dt.UTC):%Y-%m-%d %H:%MZ} ({age_h:.1f} h ago"
          f"{', STALE' if age_h > 30 else ''}), weeks {weeks[0]}-{weeks[-1]}")
    print(f"  players {counts.get('players')}, unmatched rostered "
          f"{counts.get('unmatched_rostered')}; {n_builds} builds kept; {n_ledger} rulings frozen")
    for lid, g in guard.items():
        print(f"  guard {lid}: {g}")
    return 0


def cmd_compare(args) -> int:
    from .backtest import compare
    from .backtest import render as render_backtest

    if not _need_db():
        return 1
    client = make_client()
    try:
        snap = build_snapshot(client, args.league_id)
    except (FetchError, NoBuild) as e:
        print(f"Can't build a snapshot: {e}", file=sys.stderr)
        return 2
    if not snap.league:
        print(f"No Sleeper league with id {args.league_id}.", file=sys.stderr)
        return 1
    lo, _, hi = args.weeks.partition("-")
    weeks = list(range(int(lo), int(hi or lo) + 1))
    if weeks[-1] >= snap.current_week:
        print(f"Week {weeks[-1]} isn't finished yet (current week {snap.current_week}).",
              file=sys.stderr)
        return 1
    print(render_backtest(compare(snap, client, weeks)))
    return 0


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
    for name, fn, text in (("waivers", cmd_waivers, "best free-agent adds and who to drop"),
                           ("startsit", cmd_startsit, "this week's best lineup")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("league_id")
        sp.add_argument("--team", required=True, help="Sleeper username or roster number")
        sp.set_defaults(func=fn)
    dbp = sub.add_parser("db", help="Postgres setup")
    dbp.add_argument("action", choices=["init"])
    dbp.set_defaults(func=cmd_db)
    pl = sub.add_parser("pipeline", help="run the daily build into Postgres")
    pl.add_argument("--league", action="append", help="league id (repeatable)")
    pl.set_defaults(func=cmd_pipeline)
    st = sub.add_parser("status", help="show the current daily build")
    st.set_defaults(func=cmd_status)
    cp = sub.add_parser("compare", help="backtest Sleeper projections vs the baseline")
    cp.add_argument("league_id")
    cp.add_argument("--weeks", default="6-8", help="finished weeks, e.g. 6-8")
    cp.set_defaults(func=cmd_compare)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

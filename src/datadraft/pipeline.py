"""The daily build (Milestone 2): one pass that fetches Sleeper projections and the
players dump plus the nflverse tables, writes them under a new build_id, validates the
rows, and only then flips the one-row current_build pointer (D5). A failed day leaves
yesterday's build in place; the 30 h stale notice covers the gap.

Run it once a day around 08:00 UTC, after nflverse's ~07:00 refresh:

    DATABASE_URL=... datadraft pipeline --league <league_id>"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import time
from dataclasses import dataclass, field

from . import db
from .ingest import (HISTORY_SINCE, SleeperClient, crosswalk, load_injury_history,
                     load_nflverse, nflverse_team)

MAX_WEEK = 18
KEEP_BUILDS = 14  # D5
PAYLOAD_DAYS = 14  # O6
KEEP_PLAYER = ("first_name", "last_name", "full_name", "position", "fantasy_positions",
               "team", "injury_status", "injury_body_part", "injury_start_date", "status",
               "years_exp", "age", "number")


class BuildError(Exception):
    """The build was not published; the previous one stays current."""


@dataclass
class BuildReport:
    build_id: str
    weeks: list
    counts: dict
    guard: dict
    unmatched: list = field(default_factory=list)
    pruned: dict = field(default_factory=dict)


def _projects(stats: dict) -> bool:
    """Any real projected stat. ADP and games-played keys are set for nearly everyone."""
    return any(v for k, v in (stats or {}).items() if "adp" not in k and k != "gp")


def _parquet(frame) -> bytes:
    buf = io.BytesIO()
    frame.write_parquet(buf)
    return buf.getvalue()


def run_daily(c, client: SleeperClient, league_ids: list[str], *, nflverse=load_nflverse,
              history=load_injury_history, now=time.time) -> BuildReport:
    if not league_ids:
        raise BuildError("no leagues to build for: pass --league or set DATADRAFT_LEAGUES")
    state = client.state()
    season = str(state.data.get("season"))
    week = int(state.data.get("display_week") or state.data.get("week") or 1)
    leagues = {}
    for lid in league_ids:
        league, rosters = client.league(lid), client.rosters(lid)
        if not league.data or not rosters.data:
            raise BuildError(f"Sleeper has no league {lid} (or it has no rosters)")
        leagues[lid] = (league, rosters)

    players = client.players()
    schedule = client.schedule(season)
    weeks = list(range(week, MAX_WEEK + 1))
    proj = {w: client.projections(season, w) for w in weeks}
    frames = dict(nflverse(int(season)))
    frames["injury_k"] = _injury_k(c, season, history)
    # Archive today's statuses first: status_since below must see today's row, and the
    # archive records what Sleeper said even on a day the build fails validation.
    archive_statuses(c, players.data, now())
    teams = set(frames["schedules"]["home_team"].to_list()) | \
        set(frames["schedules"]["away_team"].to_list())

    # D13: keep players rostered in an allowlisted league or projected in any week.
    rostered = {p for _, r in leagues.values() for row in r.data
                for p in (row.get("players") or []) + (row.get("reserve") or [])
                + (row.get("taxi") or [])}
    projected = {str(row["player_id"]) for f in proj.values() for row in f.data or []
                 if _projects(row.get("stats"))}
    keep = sorted((rostered | projected) & set(players.data))
    info = {p: {k: players.data[p].get(k) for k in KEEP_PLAYER if k in players.data[p]}
            for p in keep}
    for pid, since in status_since(c, {p: info[p].get("injury_status") for p in keep}).items():
        info[pid]["status_since"] = since
    xw = crosswalk(info, frames["ff_playerids"], teams)
    unmatched = sorted(p for p, (key, _) in xw.items() if key is None and p in rostered)

    parquet = {name: _parquet(f) for name, f in frames.items()}
    content = {"players": players.sha, "schedule": schedule.sha,
               **{f"proj:{w}": f.sha for w, f in proj.items()},
               **{f"nfl:{n}": hashlib.sha256(b).hexdigest() for n, b in parquet.items()}}
    stamp = dt.datetime.fromtimestamp(now(), dt.UTC).strftime("%Y%m%dT%H%M%S")
    build_id = f"{stamp}-{hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:8]}"
    as_of = min([players.fetched_at, *(f.fetched_at for f in proj.values())])

    keep_set = set(keep)
    rows = [(w, str(r["player_id"]), r) for w, f in proj.items() for r in f.data or []
            if str(r["player_id"]) in keep_set]
    counts = {"players": len(keep), "projection_rows": len(rows),
              "unmatched_rostered": len(unmatched),
              "nflverse": {n: f.height for n, f in frames.items()}}

    with c.transaction():
        c.execute("insert into builds (build_id, as_of, season, state_week, weeks, "
                  "schedule_sha, guard, counts) values (%s,%s,%s,%s,%s,%s,'{}',%s)",
                  (build_id, as_of, season, week, weeks, schedule.sha, json.dumps(counts)))
        cur = c.cursor()
        with cur.copy("copy build_players (build_id, player_id, info, nflverse_key, match) "
                      "from stdin") as cp:
            for p in keep:
                cp.write_row((build_id, p, json.dumps(info[p]), *xw[p]))
        with cur.copy("copy build_projection_rows (build_id, week, player_id, team, opponent, "
                      "last_modified) from stdin") as cp:
            for w, pid, r in rows:
                cp.write_row((build_id, w, pid, r.get("team"), r.get("opponent"),
                              r.get("last_modified")))
        n_stats = 0
        with cur.copy("copy build_projections (build_id, week, player_id, stat, value) "
                      "from stdin") as cp:
            for w, pid, r in rows:
                for k, v in (r.get("stats") or {}).items():
                    # ADP is a draft ranking, not a projected stat; ~10% of rows.
                    if isinstance(v, (int, float)) and v and "adp" not in k:
                        cp.write_row((build_id, w, pid, k, float(v)))
                        n_stats += 1
        for name, blob in parquet.items():
            c.execute("insert into build_tables (build_id, name, nrows, parquet) "
                      "values (%s,%s,%s,%s)", (build_id, name, frames[name].height, blob))
    counts["projection_stats"] = n_stats

    try:
        _validate(c, build_id, weeks, frames)
    except BuildError:
        c.execute("delete from builds where build_id = %s", (build_id,))
        raise

    guard = {lid: _guard(c, client, build_id, lid, league, rosters)
             for lid, (league, rosters) in leagues.items()}
    with c.transaction():
        c.execute("update builds set guard = %s, counts = %s where build_id = %s",
                  (json.dumps(guard), json.dumps(counts), build_id))
        c.execute("insert into current_build (one, build_id) values (true, %s) "
                  "on conflict (one) do update set build_id = excluded.build_id, "
                  "flipped_at = now()", (build_id,))
    pruned = prune(c, now())
    return BuildReport(build_id, weeks, counts, guard, unmatched, pruned)


def _validate(c, build_id: str, weeks: list, frames: dict) -> None:
    n_players, = c.execute("select count(*) from build_players where build_id = %s",
                           (build_id,)).fetchone()
    per_week = dict(c.execute("select week, count(*) from build_projections where build_id = %s "
                              "group by week", (build_id,)).fetchall())
    problems = []
    if n_players == 0:
        problems.append("no players")
    if not per_week.get(weeks[0]):
        problems.append(f"no week {weeks[0]} projections")
    for name in ("schedules", "ff_playerids"):
        if frames[name].height == 0:
            problems.append(f"nflverse {name} is empty")
    if problems:
        raise BuildError("build failed validation: " + "; ".join(problems))


def _guard(c, client, build_id, league_id, league, rosters) -> str:
    """Record whether the D19 guard passes for each league. A failing guard still
    publishes (the engine re-checks and pauses rulings); it's shown by `datadraft status`."""
    from .projections import GuardError, guard, project
    from .snapshot import from_build

    snap = from_build(c, build_id, client, league_id)
    try:
        guard(snap, project(snap), snap.current_week)
        return "ok"
    except GuardError as e:
        return str(e)


def _injury_k(c, season: str, history):
    """§5 k table. It depends only on past seasons, so reuse the current build's copy when
    it was made for the same season; otherwise load 10+ seasons of history once."""
    import polars as pl

    row = c.execute("select t.parquet from current_build cb join builds b using (build_id) "
                    "join build_tables t using (build_id) where t.name = 'injury_k' "
                    "and b.season = %s", (season,)).fetchone()
    if row:
        return pl.read_parquet(io.BytesIO(row[0]))
    from .projections import injury_k

    inj, rw = history(int(season))
    return injury_k(inj, rw, HISTORY_SINCE)


def status_since(c, current: dict) -> dict:
    """{player_id: 'YYYY-MM-DD'}: the first archived day of each injured player's current
    status. Omitted when the run reaches the archive's first day (true start unknown)."""
    hurt = [p for p, st in current.items() if st]
    if not hurt:
        return {}
    first_day = c.execute("select min(day) from status_archive").fetchone()[0]
    out = {}
    rows = c.execute("select player_id, day, injury_status from status_archive where "
                     "player_id = any(%s) order by player_id, day desc", (hurt,)).fetchall()
    run: dict = {}
    for pid, day, st in rows:
        state = run.setdefault(pid, {"open": True, "since": None})
        if not state["open"]:
            continue
        if st == current[pid]:
            state["since"] = day
        else:
            state["open"] = False
    for pid, state in run.items():
        if state["since"] is not None and (not state["open"] or state["since"] > first_day):
            out[pid] = state["since"].isoformat()
    return out


def archive_statuses(c, players: dict, ts: float) -> int:
    """One row per player per UTC day: the IR placement history §5 reads."""
    day = dt.datetime.fromtimestamp(ts, dt.UTC).date()
    rows = [(day, pid, p.get("injury_status"), nflverse_team(p.get("team")))
            for pid, p in players.items() if p.get("team") or p.get("injury_status")]
    with c.transaction():
        cur = c.cursor()
        cur.execute("create temp table _status (like status_archive) on commit drop")
        with cur.copy("copy _status (day, player_id, injury_status, team) from stdin") as cp:
            for r in rows:
                cp.write_row(r)
        cur.execute("insert into status_archive select * from _status on conflict (day, "
                    "player_id) do update set injury_status = excluded.injury_status, "
                    "team = excluded.team")
    return len(rows)


def prune(c, ts: float, keep: int = KEEP_BUILDS, days: int = PAYLOAD_DAYS) -> dict:
    """Keep the newest `keep` builds (and always the current one). Drop league-state
    payloads and snapshots older than `days`, unless a ledger ruling references them (O6)."""
    cutoff = ts - days * 86400
    with c.transaction():
        b = c.execute(
            "delete from builds where build_id not in (select build_id from builds "
            "order by created_at desc, build_id desc limit %s) and build_id not in "
            "(select build_id from current_build)", (keep,)).rowcount
        s = c.execute(
            "delete from snapshots where created_at < to_timestamp(%s) and snapshot_id not in "
            "(select snapshot_id from ledger)", (cutoff,)).rowcount
        c.execute("create temp table _held on commit drop as select v.value as sha "
                  "from snapshots s, jsonb_each_text(s.manifest->'payload_shas') v")
        i = c.execute("delete from payload_index where fetched_at < %s and sha not in "
                      "(select sha from _held)", (cutoff,)).rowcount
        p = c.execute("delete from payloads p where not exists (select 1 from payload_index i "
                      "where i.sha = p.sha) and sha not in (select sha from _held)").rowcount
    return {"builds": b, "snapshots": s, "payload_index": i, "payloads": p}

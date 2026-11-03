"""A snapshot pins everything one computation reads: league state, the players dump,
the schedule, last week's matchups and the projection rows for each horizon week. Its id
is a hash of the payload hashes, so the same id always reproduces the same numbers (§2)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

from . import db
from .ingest import PayloadStore, SleeperClient, data_dir

STALE_BUILD_S = 30 * 3600  # §2: older daily builds get a "data is stale" notice


class NoBuild(Exception):
    """Postgres mode, but no daily build has been published yet."""


@dataclass(frozen=True)
class Snapshot:
    season: str
    current_week: int
    today: dt.date
    league: dict
    rosters: list
    users: list
    players: dict
    projections: dict  # week -> list of Sleeper projection rows
    build_as_of: str  # when projections/players were fetched (UTC, ISO)
    league_as_of: str  # when rosters were fetched (UTC, ISO)
    payload_shas: dict = field(default_factory=dict)
    league_stale: bool = False
    schedule: list = field(default_factory=list)
    matchups: list = field(default_factory=list)  # most recent completed week (D19 guard)
    build_id: str = ""  # Postgres mode: the daily build this snapshot sits on (§2)
    warnings: tuple = ()  # shown with the ruling (stale build, players missing from build)
    nflverse: dict = field(default_factory=dict)  # build's nflverse frames (empty: file mode)
    xwalk: dict = field(default_factory=dict)  # player_id -> (nflverse_key, match) (D4)
    transactions: list = field(default_factory=list)  # this week's and last week's (D23)

    @property
    def snapshot_id(self) -> str:
        blob = json.dumps(self.payload_shas, sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]

    @property
    def settings(self) -> dict:
        return self.league.get("settings", {})

    @property
    def scoring(self) -> dict:
        return self.league.get("scoring_settings", {})

    @property
    def roster_positions(self) -> list:
        return self.league.get("roster_positions", [])

    def last_week(self) -> int:
        start = int(self.settings.get("playoff_week_start") or 0)
        teams = int(self.settings.get("playoff_teams") or 0)
        if start <= 0:
            return 17  # no playoffs configured: Sleeper's default final fantasy week
        rounds = max(1, (teams - 1).bit_length()) if teams > 1 else 1
        return start + rounds - 1


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%dT%H:%MZ")


def build_snapshot(client: SleeperClient, league_id: str) -> Snapshot:
    if db.enabled():
        c = db.conn()
        snap = from_build(c, current_build_id(c), client, league_id)
        if snap.league:
            save_manifest(snap)
        return snap
    state = client.state()
    league = client.league(league_id)
    if not league.data:
        return Snapshot("", 0, dt.date.today(), {}, [], [], {}, {}, "", "")
    rosters = client.rosters(league_id)
    users = client.users(league_id)
    players = client.players()
    season = str(league.data.get("season") or state.data.get("season"))
    current = int(state.data.get("display_week") or state.data.get("week") or 1)
    schedule = client.schedule(season)
    shas = {"state": state.sha, "league": league.sha, "rosters": rosters.sha,
            "users": users.sha, "players": players.sha, "schedule": schedule.sha}
    matchups = None
    if current > 1:
        matchups = client.matchups(league_id, current - 1)
        shas["matchups"] = matchups.sha
    txns = _transactions(client, league_id, current, shas)
    snap0 = Snapshot(season, current, dt.date.today(), league.data, rosters.data,
                     users.data, {}, {}, "", "")
    projections = {}
    proj_times = []
    for week in range(current, snap0.last_week() + 1):
        p = client.projections(season, week)
        projections[week] = p.data
        shas[f"proj:{week}"] = p.sha
        proj_times.append(p.fetched_at)
    league_time = min(league.fetched_at, rosters.fetched_at)
    snap = Snapshot(
        season=season,
        current_week=current,
        today=dt.datetime.fromtimestamp(rosters.fetched_at).date(),
        league=league.data,
        rosters=rosters.data,
        users=users.data,
        players=players.data,
        projections=projections,
        build_as_of=_iso(min([players.fetched_at, *proj_times])),
        league_as_of=_iso(league_time),
        payload_shas=shas,
        league_stale=league.stale or rosters.stale,
        schedule=schedule.data,
        matchups=matchups.data if matchups else [],
        transactions=txns,
    )
    save_manifest(snap)
    return snap


def _transactions(client, league_id: str, current: int, shas: dict) -> list:
    """This week's and last week's transactions: recent drops sit on waivers (D23)."""
    out = []
    for week in sorted({max(1, current - 1), current}):
        t = client.transactions(league_id, week)
        shas[f"txn:{week}"] = t.sha
        out += t.data or []
    return out


def _stored_transactions(store, shas: dict) -> list:
    return [row for k in sorted(shas) if k.startswith("txn:") for row in store.get(shas[k]) or []]


def current_build_id(c) -> str:
    row = c.execute("select build_id from current_build").fetchone()
    if row is None:
        raise NoBuild("no daily build yet: run `datadraft pipeline --league <league_id>`")
    return row[0]


def _build_players(c, build_id: str) -> tuple[dict, dict]:
    players, xwalk = {}, {}
    for pid, info, key, match in c.execute(
            "select player_id, info, nflverse_key, match from build_players "
            "where build_id = %s", (build_id,)):
        players[pid] = info
        xwalk[pid] = (key, match)
    return players, xwalk


def _build_projections(c, build_id: str, weeks) -> dict:
    """Every Sleeper row the build kept, including all-zero ones: a published 0 is still
    Sleeper's answer and must not fall through to the baseline (§1 precedence)."""
    out: dict = {w: {} for w in weeks}
    for week, pid, lm in c.execute(
            "select week, player_id, last_modified from build_projection_rows where "
            "build_id = %s and week = any(%s) order by week, player_id", (build_id, list(weeks))):
        out[week][pid] = {"player_id": pid, "week": week, "last_modified": lm, "stats": {}}
    for week, pid, stat, value in c.execute(
            "select week, player_id, stat, value from build_projections where build_id = %s "
            "and week = any(%s) order by week, player_id, stat", (build_id, list(weeks))):
        out[week][pid]["stats"][stat] = value
    return {w: list(rows.values()) for w, rows in out.items()}


NFLVERSE_IN_SNAPSHOT = ("ff_opportunity", "player_stats", "team_stats", "schedules",
                        "rosters_weekly", "injury_k")


def _build_nflverse(c, build_id: str) -> dict:
    import io

    import polars as pl

    return {name: pl.read_parquet(io.BytesIO(blob)) for name, blob in c.execute(
        "select name, parquet from build_tables where build_id = %s and name = any(%s)",
        (build_id, list(NFLVERSE_IN_SNAPSHOT)))}


def from_build(c, build_id: str, client: SleeperClient, league_id: str) -> Snapshot:
    """§2 derived snapshot: the pinned daily build plus league state fetched now."""
    b = c.execute("select as_of, season, weeks, schedule_sha from builds where build_id = %s",
                  (build_id,)).fetchone()
    if b is None:
        raise NoBuild(f"build {build_id} no longer exists")
    as_of, b_season, b_weeks, schedule_sha = b
    state = client.state()
    league = client.league(league_id)
    if not league.data:
        return Snapshot("", 0, dt.date.today(), {}, [], [], {}, {}, "", "")
    rosters = client.rosters(league_id)
    users = client.users(league_id)
    season = str(league.data.get("season") or state.data.get("season"))
    current = int(state.data.get("display_week") or state.data.get("week") or 1)
    shas = {"build": build_id, "state": state.sha, "league": league.sha,
            "rosters": rosters.sha, "users": users.sha}
    matchups = None
    if current > 1:
        matchups = client.matchups(league_id, current - 1)
        shas["matchups"] = matchups.sha
    txns = _transactions(client, league_id, current, shas)
    snap0 = Snapshot(season, current, dt.date.today(), league.data, rosters.data,
                     users.data, {}, {}, "", "")
    weeks = [w for w in range(current, snap0.last_week() + 1) if w in b_weeks]
    if season != b_season:
        raise NoBuild(f"today's build is for {b_season}, this league is {season}")
    players, xwalk = _build_players(c, build_id)
    warnings = []
    rostered = {p for r in rosters.data for p in (r.get("players") or [])}
    missing = sorted(rostered - set(players))
    if missing:
        warnings.append(f"{len(missing)} rostered players aren't in today's build; add this "
                        "league to DATADRAFT_LEAGUES so the pipeline keeps them.")
    if client.now() - as_of > STALE_BUILD_S:
        warnings.append(f"Data is stale: projections are from {_iso(as_of)}, over 30 h ago.")
    return Snapshot(
        season=season,
        current_week=current,
        today=dt.datetime.fromtimestamp(rosters.fetched_at).date(),
        league=league.data,
        rosters=rosters.data,
        users=users.data,
        players=players,
        projections=_build_projections(c, build_id, weeks),
        build_as_of=_iso(as_of),
        league_as_of=_iso(min(league.fetched_at, rosters.fetched_at)),
        payload_shas=shas,
        league_stale=league.stale or rosters.stale,
        schedule=db.PgPayloadStore(c).get(schedule_sha),
        matchups=matchups.data if matchups else [],
        build_id=build_id,
        warnings=tuple(warnings),
        nflverse=_build_nflverse(c, build_id),
        xwalk=xwalk,
        transactions=txns,
    )


def _manifest(snap: Snapshot) -> dict:
    return {"season": snap.season, "current_week": snap.current_week,
            "today": snap.today.isoformat(), "build_as_of": snap.build_as_of,
            "league_as_of": snap.league_as_of, "league_stale": snap.league_stale,
            "payload_shas": snap.payload_shas, "build_id": snap.build_id,
            "weeks": sorted(snap.projections), "warnings": list(snap.warnings)}


def save_manifest(snap: Snapshot) -> None:
    if db.enabled():
        db.conn().execute("insert into snapshots (snapshot_id, build_id, manifest) values "
                          "(%s, %s, %s) on conflict do nothing",
                          (snap.snapshot_id, snap.build_id, json.dumps(_manifest(snap))))
        return
    root = data_dir() / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"season": snap.season, "current_week": snap.current_week,
                "today": snap.today.isoformat(), "build_as_of": snap.build_as_of,
                "league_as_of": snap.league_as_of, "league_stale": snap.league_stale,
                "payload_shas": snap.payload_shas}
    (root / f"{snap.snapshot_id}.json").write_text(json.dumps(manifest, indent=1))


def load_snapshot(snapshot_id: str) -> Snapshot:
    """Rebuild a saved snapshot from its stored payloads (no network)."""
    if db.enabled():
        return _load_from_db(db.conn(), snapshot_id)
    m = json.loads((data_dir() / "snapshots" / f"{snapshot_id}.json").read_text())
    store = PayloadStore(data_dir())
    shas = m["payload_shas"]
    projections = {int(k.split(":")[1]): store.get(v) for k, v in shas.items()
                   if k.startswith("proj:")}
    return Snapshot(m["season"], m["current_week"], dt.date.fromisoformat(m["today"]),
                    store.get(shas["league"]), store.get(shas["rosters"]),
                    store.get(shas["users"]), store.get(shas["players"]), projections,
                    m["build_as_of"], m["league_as_of"], shas, m["league_stale"],
                    store.get(shas["schedule"]),
                    store.get(shas["matchups"]) if "matchups" in shas else [],
                    transactions=_stored_transactions(store, shas))


def _load_from_db(c, snapshot_id: str) -> Snapshot:
    row = c.execute("select manifest from snapshots where snapshot_id = %s",
                    (snapshot_id,)).fetchone()
    if row is None:
        raise KeyError(f"no snapshot {snapshot_id}")
    m = row[0]
    shas, build_id = m["payload_shas"], m["build_id"]
    store = db.PgPayloadStore(c)
    sched = c.execute("select schedule_sha from builds where build_id = %s", (build_id,)).fetchone()
    if sched is None:
        raise NoBuild(f"snapshot {snapshot_id} used build {build_id}, which has been pruned")
    players, xwalk = _build_players(c, build_id)
    return Snapshot(m["season"], m["current_week"], dt.date.fromisoformat(m["today"]),
                    store.get(shas["league"]), store.get(shas["rosters"]),
                    store.get(shas["users"]), players,
                    _build_projections(c, build_id, m["weeks"]), m["build_as_of"],
                    m["league_as_of"], shas, m["league_stale"], store.get(sched[0]),
                    store.get(shas["matchups"]) if "matchups" in shas else [],
                    build_id, tuple(m.get("warnings") or ()), _build_nflverse(c, build_id), xwalk,
                    _stored_transactions(store, shas))

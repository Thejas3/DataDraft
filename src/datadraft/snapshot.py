"""A snapshot pins everything one computation reads: league state, the players dump,
the schedule, last week's matchups and the projection rows for each horizon week. Its id
is a hash of the payload hashes, so the same id always reproduces the same numbers (§2)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass, field

from .ingest import PayloadStore, SleeperClient, data_dir


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
    state = client.state()
    league = client.league(league_id)
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
    )
    save_manifest(snap)
    return snap


def save_manifest(snap: Snapshot) -> None:
    root = data_dir() / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"season": snap.season, "current_week": snap.current_week,
                "today": snap.today.isoformat(), "build_as_of": snap.build_as_of,
                "league_as_of": snap.league_as_of, "league_stale": snap.league_stale,
                "payload_shas": snap.payload_shas}
    (root / f"{snap.snapshot_id}.json").write_text(json.dumps(manifest, indent=1))


def load_snapshot(snapshot_id: str) -> Snapshot:
    """Rebuild a saved snapshot from its stored payloads (no network)."""
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
                    store.get(shas["matchups"]) if "matchups" in shas else [])

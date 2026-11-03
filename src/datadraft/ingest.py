"""Sleeper ingest: fetch league state, players and projections, and keep every raw
payload as a hash-named JSON file so any snapshot can be rebuilt later (D20)."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

API = "https://api.sleeper.app"
PROJECTION_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
STALE_LIMIT_S = 24 * 3600  # D9: fall back to stored league state under 24 h old


def data_dir() -> Path:
    return Path(os.environ.get("DATADRAFT_HOME", Path.home() / ".datadraft"))


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class Fetched:
    data: object
    sha: str
    fetched_at: float
    stale: bool = False


class PayloadStore:
    """Content-addressed payloads plus an append-only index of (key, sha, fetched_at)."""

    def __init__(self, root: Path):
        self.root = root
        (root / "payloads").mkdir(parents=True, exist_ok=True)
        self.index = root / "index.jsonl"

    def put(self, key: str, raw: bytes, fetched_at: float) -> str:
        sha = hashlib.sha256(raw).hexdigest()
        path = self.root / "payloads" / f"{sha}.json"
        if not path.exists():
            path.write_bytes(raw)
        with self.index.open("a") as f:
            f.write(json.dumps({"key": key, "sha": sha, "fetched_at": fetched_at}) + "\n")
        return sha

    def get(self, sha: str) -> object:
        return json.loads((self.root / "payloads" / f"{sha}.json").read_bytes())

    def latest(self, key: str) -> Fetched | None:
        if not self.index.exists():
            return None
        found = None
        for line in self.index.read_text().splitlines():
            row = json.loads(line)
            if row["key"] == key:
                found = row
        if found is None:
            return None
        return Fetched(self.get(found["sha"]), found["sha"], found["fetched_at"])


class SleeperClient:
    """Read-only client for Sleeper's public API. Each request times out after 10 s and
    is retried once; league-state requests fall back to the last stored copy if it is
    under 24 h old, and that copy is marked stale so the ruling can say so."""

    def __init__(self, store: PayloadStore, timeout: float = 10.0, now=time.time):
        self.store = store
        self.timeout = timeout
        self.now = now

    def _http(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "datadraft/0.1"})
        last_err: Exception | None = None
        for _ in range(2):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:  # malformed id: same as Sleeper's `null` for unknown ones
                    return b"null"
                last_err = e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = e
        raise FetchError(f"Sleeper didn't respond for {url}: {last_err}")

    def _get(self, path: str, max_age: float | None = None, stale_ok: bool = True) -> Fetched:
        if max_age is not None:
            cached = self.store.latest(path)
            if cached and self.now() - cached.fetched_at < max_age:
                return cached
        try:
            raw = self._http(API + path)
        except FetchError:
            cached = self.store.latest(path)
            if stale_ok and cached and self.now() - cached.fetched_at < STALE_LIMIT_S:
                return Fetched(cached.data, cached.sha, cached.fetched_at, stale=True)
            raise
        fetched_at = self.now()
        sha = self.store.put(path, raw, fetched_at)
        return Fetched(json.loads(raw), sha, fetched_at)

    def state(self) -> Fetched:
        return self._get("/v1/state/nfl", max_age=3600)

    def user(self, username: str) -> Fetched:
        return self._get(f"/v1/user/{username}", max_age=7 * 24 * 3600)

    def leagues(self, user_id: str, season: str) -> Fetched:
        return self._get(f"/v1/user/{user_id}/leagues/nfl/{season}", max_age=3600)

    def league(self, league_id: str) -> Fetched:
        return self._get(f"/v1/league/{league_id}")

    def rosters(self, league_id: str) -> Fetched:
        return self._get(f"/v1/league/{league_id}/rosters")

    def users(self, league_id: str) -> Fetched:
        return self._get(f"/v1/league/{league_id}/users")

    def matchups(self, league_id: str, week: int) -> Fetched:
        return self._get(f"/v1/league/{league_id}/matchups/{week}")

    def schedule(self, season: str) -> Fetched:
        # Undocumented but public: one row per game with date, teams and status.
        return self._get(f"/schedule/nfl/regular/{season}", max_age=3600)

    def players(self) -> Fetched:
        # The full dump is ~5 MB; Sleeper asks callers to fetch it at most once a day.
        return self._get("/v1/players/nfl", max_age=24 * 3600)

    def stats(self, season: str, week: int) -> Fetched:
        """Actual weekly stat lines, same shape as projections (backtests only)."""
        pos = "&".join(f"position[]={p}" for p in PROJECTION_POSITIONS)
        return self._get(f"/stats/nfl/{season}/{week}?season_type=regular&{pos}", max_age=6 * 3600)

    def projections(self, season: str, week: int) -> Fetched:
        pos = "&".join(f"position[]={p}" for p in PROJECTION_POSITIONS)
        return self._get(
            f"/projections/nfl/{season}/{week}?season_type=regular&{pos}", max_age=12 * 3600
        )


# --- nflverse + ID crosswalk (Milestone 2, D4) --------------------------------------

# nflverse names the Rams "LA"; every other Sleeper team abbreviation matches.
SLEEPER_TO_NFLVERSE_TEAM = {"LAR": "LA"}


def load_nflverse(season: int) -> dict:
    """The nflverse tables a build pins, as polars frames. Raises on any failure, so a
    half-fetched day never gets published (D5)."""
    import nflreadpy as nfl

    return {
        "schedules": nfl.load_schedules(season),
        "injuries": nfl.load_injuries(season),
        "ff_opportunity": nfl.load_ff_opportunity(season),
        "player_stats": nfl.load_player_stats(season),
        "team_stats": nfl.load_team_stats(season),
        "rosters_weekly": nfl.load_rosters_weekly(season),
        "ff_playerids": nfl.load_ff_playerids(),
    }


HISTORY_SINCE = 2015


def load_injury_history(season: int):
    """(injury reports, weekly rosters) for HISTORY_SINCE..season-1: the §5 k table input."""
    import polars as pl
    import nflreadpy as nfl

    seasons = list(range(HISTORY_SINCE, season))
    cols_i = ["season", "week", "game_type", "gsis_id", "position", "report_status",
              "report_primary_injury"]
    cols_r = ["season", "week", "game_type", "gsis_id", "position", "status"]
    inj = pl.concat([nfl.load_injuries(s).select(cols_i) for s in seasons], how="vertical_relaxed")
    rw = pl.concat([nfl.load_rosters_weekly(s).select(cols_r) for s in seasons],
                   how="vertical_relaxed")
    return inj, rw


def nflverse_team(team: str | None) -> str | None:
    return SLEEPER_TO_NFLVERSE_TEAM.get(team, team) if team else None


def crosswalk(players: dict, ids, teams: set) -> dict[str, tuple[str | None, str | None]]:
    """D4: {sleeper_id: (nflverse_key, match)}. Skill players and kickers match by
    sleeper_id -> gsis_id through ff_playerids; DEF (and kickers with no gsis id) match by
    team abbreviation. Unmatched players map to (None, None): they keep Sleeper-only data
    and their nflverse-derived fields are marked 'no nflverse match'."""
    import polars as pl

    gsis = dict(
        ids.filter(pl.col("sleeper_id").is_not_null() & pl.col("gsis_id").is_not_null())
        .select(pl.col("sleeper_id").cast(pl.Utf8), "gsis_id").iter_rows())
    out = {}
    for pid, info in players.items():
        pos = set(info.get("fantasy_positions") or [info.get("position")])
        team = nflverse_team(pid if "DEF" in pos else info.get("team"))
        if "DEF" in pos:
            out[pid] = (team, "team") if team in teams else (None, None)
        elif pid in gsis:
            out[pid] = (gsis[pid], "gsis")
        elif "K" in pos and team in teams:
            out[pid] = (team, "team")
        else:
            out[pid] = (None, None)
    return out

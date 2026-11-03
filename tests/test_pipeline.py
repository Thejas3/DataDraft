"""Milestone 2 storage: the daily build, the pointer flip, pruning, and Postgres-backed
snapshots that reproduce the file-mode numbers exactly. Needs a Postgres; set
DATADRAFT_TEST_DATABASE_URL (default: the docker-compose one). Skipped if none is up.
Each test gets its own schema, so runs never see each other's rows."""

import copy
import json
import os
import uuid

import polars as pl
import pytest

from conftest import from_recorded
from datadraft import db
from datadraft.engine import evaluate
from datadraft.ingest import FetchError, SleeperClient, crosswalk
from datadraft.pipeline import BuildError, prune, run_daily
from datadraft.snapshot import build_snapshot, load_snapshot

TEST_URL = os.environ.get("DATADRAFT_TEST_DATABASE_URL",
                          "postgresql://datadraft:datadraft@localhost:5433/datadraft")
TRADE = "Marvin Harrison Jr., Dalton Kincaid for MarShawn Lloyd"
DAY = 1793260800.0  # 2026-10-29 08:00 UTC, the day the fixture was recorded


@pytest.fixture
def pg(monkeypatch):
    try:
        c = db.connect(TEST_URL)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no test Postgres at {TEST_URL}: {e}")
    schema = f"t_{uuid.uuid4().hex[:10]}"
    c.execute(f"create schema {schema}")
    c.execute(f"set search_path to {schema}")
    db.init(c)
    db.use(c)
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    yield c
    c.execute(f"drop schema {schema} cascade")
    db.use(None)
    c.close()


class FakeSleeper(SleeperClient):
    """Serves the recorded league (as redraft) instead of calling Sleeper (D11)."""

    def __init__(self, store, raw, clock):
        super().__init__(store, now=clock)
        league = copy.deepcopy(raw["league"])
        league["settings"]["type"] = 0
        players = copy.deepcopy(raw["players"])
        players["999"] = {"full_name": "Free Agent", "position": "WR",
                          "fantasy_positions": ["WR"], "team": None, "injury_status": None}
        self.routes = {
            "/v1/state/nfl": {"season": raw["season"], "week": raw["current_week"],
                              "display_week": raw["current_week"]},
            "/v1/league/fixture": league,
            "/v1/league/fixture/rosters": raw["rosters"],
            "/v1/league/fixture/users": raw["users"],
            f"/v1/league/fixture/matchups/{raw['current_week'] - 1}": raw["matchups"],
            "/v1/players/nfl": players,
            f"/schedule/nfl/regular/{raw['season']}": raw["schedule"],
        }
        self.projections_by_week = raw["projections"]
        self.down = False

    def _http(self, url):
        if self.down:
            raise FetchError("down")
        path = url.removeprefix("https://api.sleeper.app")
        if path.startswith("/projections/"):
            week = path.split("?")[0].rsplit("/", 1)[1]
            return json.dumps(self.projections_by_week.get(week, [])).encode()
        if path not in self.routes:
            return b"null"
        return json.dumps(self.routes[path]).encode()


def fake_nflverse(season):
    return {
        "schedules": pl.DataFrame({"home_team": ["CAR", "LA"], "away_team": ["CHI", "ARI"]}),
        "injuries": pl.DataFrame({"gsis_id": ["00-1"], "report_status": ["Out"]}),
        "ff_opportunity": pl.DataFrame({"player_id": ["00-1"], "week": [7]}),
        "player_stats": pl.DataFrame({"player_id": ["00-1"], "week": [7]}),
        "team_stats": pl.DataFrame({"team": ["CAR"], "week": [7]}),
        "ff_playerids": pl.DataFrame({"sleeper_id": [5995, None], "gsis_id": ["00-1", "00-2"]}),
    }


class Clock:
    def __init__(self, t=DAY):
        self.t = t

    def __call__(self):
        return self.t


def build(pg, recorded_raw, clock=None):
    clock = clock or Clock()
    client = FakeSleeper(db.PgPayloadStore(pg), recorded_raw, clock)
    return client, run_daily(pg, client, ["fixture"], nflverse=fake_nflverse, now=clock)


def current(pg):
    return pg.execute("select build_id from current_build").fetchone()[0]


def test_pipeline_publishes_and_db_snapshot_matches_file_mode(pg, recorded_raw):
    client, rep = build(pg, recorded_raw)
    assert current(pg) == rep.build_id
    assert rep.guard == {"fixture": "ok"}
    assert rep.counts["players"] == 310  # D13: the unrostered, unprojected FA is pruned
    snap = build_snapshot(client, "fixture")
    assert snap.build_id == rep.build_id and snap.warnings == ()
    res = evaluate({"type": "trade", "text": TRADE}, snap.snapshot_id, snapshot=snap,
                   use_court=False)
    file_mode = evaluate({"type": "trade", "text": TRADE}, "x",
                         snapshot=from_recorded(recorded_raw, league_type=0), use_court=False,
                         freeze=False)
    assert (res.ruling.verdict, res.ruling.delta.me.delta, res.ruling.delta.them.delta) == \
        (file_mode.ruling.verdict, file_mode.ruling.delta.me.delta, file_mode.ruling.delta.them.delta)
    assert res.ruling.delta.me.per_week == file_mode.ruling.delta.me.per_week
    # The ledger row and the snapshot reload from Postgres alone, with no network.
    client.down = True
    again = evaluate({"type": "trade", "text": TRADE}, snap.snapshot_id, use_court=False)
    assert again.ruling.delta.me.per_week == res.ruling.delta.me.per_week
    assert pg.execute("select count(*) from ledger").fetchone()[0] == 1
    assert load_snapshot(snap.snapshot_id).players == snap.players


def test_failed_validation_keeps_previous_build(pg, recorded_raw):
    _, first = build(pg, recorded_raw)
    broken = copy.deepcopy(recorded_raw)
    broken["projections"] = {w: [] for w in broken["projections"]}
    with pytest.raises(BuildError, match="no week 8 projections"):
        build(pg, broken, Clock(DAY + 86400))
    assert current(pg) == first.build_id
    assert pg.execute("select count(*) from builds").fetchone()[0] == 1


def test_stale_build_and_missing_players_warn(pg, recorded_raw):
    client, _ = build(pg, recorded_raw)
    pg.execute("delete from build_players where player_id = %s",
               (recorded_raw["rosters"][0]["players"][0],))
    client.now = Clock(DAY + 31 * 3600)
    snap = build_snapshot(client, "fixture")
    assert any("stale" in w for w in snap.warnings)
    assert any("1 rostered players" in w for w in snap.warnings)


def test_status_archive_one_row_per_player_per_day(pg, recorded_raw):
    build(pg, recorded_raw)
    build(pg, recorded_raw, Clock(DAY + 3600))  # same UTC day: upsert, not duplicate
    build(pg, recorded_raw, Clock(DAY + 86400))
    days = dict(pg.execute("select day::text, count(*) from status_archive group by day"))
    assert days == {"2026-10-29": 310, "2026-10-30": 310}


def test_prune_keeps_14_builds_and_ledger_payloads(pg, recorded_raw):
    client, _ = build(pg, recorded_raw)
    snap = build_snapshot(client, "fixture")
    evaluate({"type": "trade", "text": TRADE}, snap.snapshot_id, snapshot=snap, use_court=False)
    for d in range(1, 16):
        build(pg, recorded_raw, Clock(DAY + d * 86400))
    assert pg.execute("select count(*) from builds").fetchone()[0] == 14
    prune(pg, DAY + 60 * 86400)
    # The ruling's league-state payloads survive; everything else past 14 days is gone.
    kept = {r[0] for r in pg.execute("select sha from payloads")}
    assert {snap.payload_shas[k] for k in ("league", "rosters", "users")} <= kept
    assert pg.execute("select count(*) from snapshots").fetchone()[0] == 1


def test_crosswalk_matches_gsis_def_by_team_and_flags_the_rest():
    players = {"5995": {"position": "RB", "team": "CAR"},
               "LAR": {"position": "DEF", "fantasy_positions": ["DEF"]},
               "17": {"position": "K", "team": "CHI"},
               "42": {"position": "WR", "team": "CAR"}}
    ids = pl.DataFrame({"sleeper_id": [5995], "gsis_id": ["00-1"]})
    assert crosswalk(players, ids, {"CAR", "CHI", "LA"}) == {
        "5995": ("00-1", "gsis"), "LAR": ("LA", "team"), "17": ("CHI", "team"),
        "42": (None, None)}

import copy
import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest

from datadraft.snapshot import Snapshot

FIXTURES = Path(__file__).parent / "fixtures"
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "BN"]
GUARD_KEYS = {"pass_yd": 0, "rush_yd": 0, "rec_yd": 0, "rec": 0}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("DATADRAFT_HOME", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)  # file mode unless a test opts in
    from datadraft.engine import clear_caches

    clear_caches()  # tests reuse build ids across schemas; production ids are unique
    return tmp_path


def synthetic(rosters: dict, points: dict, *, weeks=(9, 10), current=9, today="2026-11-03",
              settings=None, positions=None, status=None, schedule=None, slots=SLOTS) -> Snapshot:
    """rosters: {roster_id: [player_id]}; points: {player_id: pts every week, or {week: pts}}.
    Player ids look like 'RB1', and the letters are the position unless overridden."""
    positions = positions or {}
    status = status or {}
    players = {}
    for pid in {p for ps in rosters.values() for p in ps}:
        pos = positions.get(pid) or pid.rstrip("0123456789")
        players[pid] = {"first_name": pid, "last_name": "Player", "full_name": f"{pid} Player",
                        "position": pos, "fantasy_positions": [pos], "team": "AAA",
                        "injury_status": status.get(pid)}
    projections = {}
    for w in weeks:
        rows = []
        for pid, pts in points.items():
            v = pts.get(w, 0) if isinstance(pts, dict) else pts
            rows.append({"player_id": pid, "week": w, "stats": {"pts": v, **GUARD_KEYS}})
        projections[w] = rows
    if schedule is None:
        schedule = [{"week": w, "home": "AAA", "away": "BBB", "status": "pre_game",
                     "date": (dt.date.fromisoformat(today) + dt.timedelta(days=5 + 7 * (w - current))).isoformat()}
                    for w in weeks]
    league = {"league_id": "synthetic", "season": "2026", "roster_positions": slots,
              "scoring_settings": {"pts": 1.0},
              "settings": {"type": 0, "playoff_week_start": weeks[-1], "playoff_teams": 0,
                           "trade_deadline": 11, "trade_review_days": 0, **(settings or {})}}
    rs = [{"roster_id": rid, "owner_id": f"u{rid}", "players": list(ps), "reserve": [], "taxi": [],
           "starters": []} for rid, ps in rosters.items()]
    users = [{"user_id": f"u{rid}", "display_name": f"Team {rid}", "metadata": {}} for rid in rosters]
    return Snapshot("2026", current, dt.date.fromisoformat(today), league, rs, users, players,
                    projections, "2026-11-03T08:00Z", "2026-11-03T08:00Z",
                    {"synthetic": json.dumps([rosters, points], sort_keys=True, default=str)},
                    schedule=schedule, matchups=[])


@pytest.fixture(scope="session")
def recorded_raw() -> dict:
    return json.loads((FIXTURES / "league_2026_w8.json").read_text())


def from_recorded(raw: dict, *, league_type=None) -> Snapshot:
    league = copy.deepcopy(raw["league"])
    if league_type is not None:
        league["settings"]["type"] = league_type
    projections = {int(w): rows for w, rows in raw["projections"].items()}
    return Snapshot(raw["season"], raw["current_week"], dt.date.fromisoformat(raw["today"]),
                    league, raw["rosters"], raw["users"], raw["players"], projections,
                    raw["build_as_of"], raw["league_as_of"], {"fixture": "league_2026_w8"},
                    schedule=raw["schedule"], matchups=raw["matchups"])


@pytest.fixture
def recorded(recorded_raw) -> Snapshot:
    """The recorded dynasty league, treated as redraft so the full path runs."""
    return from_recorded(recorded_raw, league_type=0)


def replace(snap, **kw):
    return dataclasses.replace(snap, **kw)


# --- nflverse fakes with the real column names the baseline reads ---------------------

def nfl_frames(*, season=2026, opportunity=(), player_stats=(), team_games=(), schedules=(),
               rosters_weekly=(), injury_k=()):
    """Small nflverse tables. opportunity rows: (gsis, week, {exp_col: value});
    player_stats rows: (gsis, week, {col: value}); team_games: (game_id, week, home, away,
    home_score, away_score, {team: {col: value}}); injury_k: (designation, category, n, k)."""
    import polars as pl

    from datadraft.projections import EXPECTED

    opp = [{"season": season, "week": float(w), "player_id": g, "posteam": "AAA",
            **{c: 0.0 for c in EXPECTED.values()}, **vals} for g, w, vals in opportunity]
    ps_cols = ["sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost",
               "passing_2pt_conversions", "rushing_2pt_conversions", "receiving_2pt_conversions",
               "fg_made", "fg_att", "fg_missed", "fg_made_0_19", "fg_made_20_29", "fg_made_30_39",
               "fg_made_40_49", "fg_made_50_59", "fg_made_60_", "fg_missed_0_19",
               "fg_missed_20_29", "fg_missed_30_39", "fg_missed_40_49", "fg_missed_50_59",
               "fg_missed_60_", "fg_made_distance", "pat_made", "pat_missed", "pat_att"]
    ps = [{"player_id": g, "season": season, "week": w, "season_type": "REG",
           **{c: 0 for c in ps_cols}, **vals} for g, w, vals in player_stats]
    ts_cols = ["def_sacks", "def_interceptions", "fumble_recovery_opp", "def_tds",
               "def_safeties", "def_fumbles_forced", "def_fg_blocks", "def_punt_blocks",
               "special_teams_tds", "passing_yards", "sack_yards_lost", "rushing_yards"] + ps_cols
    ts, sched = [], []
    for gid, w, home, away, hs, as_, stats in team_games:
        sched.append({"game_id": gid, "week": w, "home_team": home, "away_team": away,
                      "home_score": hs, "away_score": as_})
        for team in (home, away):
            ts.append({"season": season, "week": w, "team": team, "season_type": "REG",
                       "game_id": gid, **{c: 0 for c in ts_cols}, **stats.get(team, {})})
    sched += [dict(s) for s in schedules]

    text = {"player_id", "season_type", "game_id", "team", "home_team", "away_team",
            "gsis_id", "status", "game_type", "position", "posteam", "designation", "category"}

    def frame(rows, cols):
        if rows:
            return pl.DataFrame(rows)
        return pl.DataFrame(schema={c: pl.Utf8 if c in text else pl.Float64 for c in cols})

    return {
        "ff_opportunity": frame(opp, ["season", "week", "player_id", *EXPECTED.values()]),
        "player_stats": frame(ps, ["player_id", "season", "week", "season_type", *ps_cols]),
        "team_stats": frame(ts, ["season", "week", "team", "season_type", "game_id", *ts_cols]),
        "schedules": frame(sched, ["game_id", "week", "home_team", "away_team", "home_score",
                                   "away_score"]),
        "rosters_weekly": frame([{"season": season, "week": w, "gsis_id": g, "status": s,
                                  "game_type": "REG", "position": "WR"}
                                 for g, w, s in rosters_weekly],
                                ["season", "week", "gsis_id", "status", "game_type", "position"]),
        "injury_k": frame([{"designation": d, "category": c, "n": n, "k": k, "since": 2015}
                           for d, c, n, k in injury_k],
                          ["designation", "category", "n", "k", "since"]),
    }

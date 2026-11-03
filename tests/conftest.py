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

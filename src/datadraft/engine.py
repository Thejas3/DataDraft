"""The one public entry point (D7): evaluate(action, snapshot_id) -> Result.

The CLI (and later the API) builds or names a snapshot and calls this; nothing outside
the engine imports the other modules. Actions:
  {"type": "trade", "text": "A, B for C"}
  {"type": "waiver", "roster_id": N}
  {"type": "startsit", "roster_id": N, "live": <current-week matchup>, "live_as_of": ISO,
   "now": epoch seconds}
Only trades are frozen in the ledger; start/sit reads live fields and is never ledgered."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from . import court, ledger
from .decide import BAND, Ruling, StartSit, Waivers, rule, start_sit, waivers
from .delta import Evaluator, Invalid, horizon, parse_trade, player_name, trade_from_ids
from .lineup import unsupported_slots
from .projections import Availability, GuardError, guard, positions, project
from .snapshot import Snapshot, load_snapshot

__all__ = ["evaluate", "Result", "BAND", "player_name", "positions", "player_profile",
           "copy_dm", "clear_caches"]

LEAGUE_TYPES = {0: "redraft", 1: "keeper", 2: "dynasty"}
PICK_OR_FAAB = re.compile(r"\b(pick|round|rd|1st|2nd|3rd|faab)\b|\$", re.I)


@dataclass
class Result:
    ruling: Ruling
    snapshot: Snapshot
    matrix: dict = field(default_factory=dict)
    court: court.CourtResult | None = None
    ledger_key: str = ""
    error: str = ""  # set when no ruling can be made at all (guard tripped)
    waivers: Waivers | None = None
    startsit: StartSit | None = None
    notes: list = field(default_factory=list)  # waiver / start-sit notices
    evidence: list = field(default_factory=list)  # court bundle: [{id, label, value}]


def _unsupported(snap: Snapshot, text: str) -> str:
    """D16: refuse what the engine can't value rather than value it wrongly."""
    kind = int(snap.settings.get("type") or 0)
    if kind != 0:
        return f"{LEAGUE_TYPES.get(kind, 'this')} leagues aren't supported yet (redraft only)"
    if PICK_OR_FAAB.search(text):
        return "trades with draft picks or FAAB aren't supported yet"
    slots = unsupported_slots(snap.roster_positions)
    if slots:
        return f"lineup slots {', '.join(slots)} (e.g. IDP) aren't supported yet"
    return ""


_MATRICES: "OrderedDict[tuple, tuple]" = OrderedDict()
MATRIX_CACHE = 8  # a few leagues x the current and previous build
_LOCK = threading.Lock()


def _matrix_key(snap: Snapshot, week: int):
    """D14: builds are immutable once published, so a matrix is a pure function of the
    build and the league inputs project() reads. Rosters don't enter it. File-mode
    snapshots have no build id and are never cached."""
    if not snap.build_id:
        return None
    league = json.dumps([snap.scoring, snap.current_week, sorted(snap.projections), week,
                         snap.payload_shas.get("state")], sort_keys=True)
    return snap.build_id, hashlib.sha256(league.encode()).hexdigest()


def _matrix(snap: Snapshot, week: int) -> tuple[dict, str, str]:
    """(matrix, fallback note, error). R3/O5: a failed guard falls back to the baseline in
    Postgres mode, and pauses in file mode (no baseline)."""
    key = _matrix_key(snap, week)
    with _LOCK:
        if key is not None and key in _MATRICES:
            _MATRICES.move_to_end(key)
            return _MATRICES[key]
    matrix = project(snap)
    out = (matrix, "", "")
    try:
        guard(snap, matrix, week)
    except GuardError as e:
        if not snap.nflverse:
            out = (matrix, "", f"Projections look wrong today; rulings paused ({e}).")
        else:
            out = (project(snap, use_sleeper=False),
                   f"Sleeper projections look wrong today ({e}), so every number uses the "
                   "nflverse baseline.", "")
    if key is not None:
        with _LOCK:
            _MATRICES[key] = out
            while len(_MATRICES) > MATRIX_CACHE:
                _MATRICES.popitem(last=False)
    return out


def clear_caches() -> None:
    from . import snapshot

    with _LOCK:
        _MATRICES.clear()
    snapshot.clear_caches()


def player_profile(snap: Snapshot, pid: str) -> dict | None:
    """Projections by week with their sources, the §5 estimated-return note (the same
    function the math uses), and this season's weekly nflverse usage."""
    info = snap.players.get(pid)
    if info is None:
        return None
    matrix, fallback, _ = _matrix(snap, snap.current_week)
    weeks = []
    for w in sorted(matrix):
        c = matrix[w].get(pid)
        if c is not None:
            weeks.append({"week": w, "points": c.points, "source": c.source,
                          "availability": c.availability, "approx": c.approx})
    key, match = snap.xwalk.get(pid) or (None, None)
    usage = []
    ps = (snap.nflverse or {}).get("player_stats")
    if ps is not None and match == "gsis":
        cols = [c for c in ("week", "targets", "receptions", "receiving_yards", "carries",
                            "rushing_yards", "attempts", "passing_yards", "fantasy_points_ppr")
                if c in ps.columns]
        usage = ps.filter(ps["player_id"] == key).sort("week").select(cols).to_dicts()
    a = Availability(snap).absence(pid)
    return {"player_id": pid, "name": player_name(snap.players, pid),
            "positions": sorted(positions(snap.players, pid)), "team": info.get("team"),
            "injury_status": info.get("injury_status"),
            "injury_body_part": info.get("injury_body_part"),
            "status_as_of": snap.build_as_of, "estimated_return": a.note or None,
            "nflverse_match": bool(key), "projections": weeks, "usage": usage,
            "notes": [fallback] if fallback else []}


def copy_dm(snap: Snapshot, c) -> str:
    """§4: a template over the counteroffer's numbers, not LLM prose."""
    names = lambda ps: ", ".join(player_name(snap.players, p) for p in ps)  # noqa: E731
    return (f"Would you do {names(c.trade.give)} for {names(c.trade.get)}? "
            f"By my projections it's about {c.them.delta:+.1f} pts/wk for your lineup "
            f"through the playoffs.")


NFLVERSE_TO_SLEEPER_TEAM = {"LA": "LAR"}


def kickoffs(snap: Snapshot) -> dict:
    """{sleeper team: kickoff epoch} for the current week, from nflverse schedules
    (gameday + gametime, US Eastern). Empty in file mode."""
    sched = (snap.nflverse or {}).get("schedules")
    if sched is None or "gametime" not in sched.columns:
        return {}
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    out = {}
    for week, day, clock, home, away in sched.select(
            "week", "gameday", "gametime", "home_team", "away_team").iter_rows():
        if int(week) != snap.current_week or not day or not clock:
            continue
        t = dt.datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=et).timestamp()
        for team in (home, away):
            out[NFLVERSE_TO_SLEEPER_TEAM.get(team, team)] = t
    return out


def _status_epoch(snap: Snapshot) -> float | None:
    try:
        return dt.datetime.strptime(snap.build_as_of, "%Y-%m-%dT%H:%MZ").replace(
            tzinfo=dt.UTC).timestamp()
    except ValueError:
        return None


def _roster_action(action: dict, snap: Snapshot) -> Result:
    reason = _unsupported(snap, "")
    if reason:
        return Result(Ruling("UNSUPPORTED", reason), snap, error=reason)
    rid = int(action["roster_id"])
    if not any(int(r["roster_id"]) == rid for r in snap.rosters):
        return Result(Ruling("INVALID", f"roster {rid} isn't in this league"), snap,
                      error=f"roster {rid} isn't in this league")
    if snap.current_week > snap.last_week():
        return Result(Ruling("INVALID", "season over"), snap, error="the season is over")
    matrix, fallback, error = _matrix(snap, snap.current_week)
    if error:
        return Result(Ruling("INVALID"), snap, matrix, error=error)
    res = Result(Ruling("INVALID"), snap, matrix)
    if action["type"] == "waiver":
        res.waivers = waivers(snap, matrix, rid)
    else:
        res.startsit = start_sit(snap, matrix, rid, action.get("live") or {},
                                 now=action.get("now", time.time()),
                                 live_as_of=action.get("live_as_of", ""),
                                 kickoffs=kickoffs(snap), status_as_of=_status_epoch(snap))
    res.notes = ([fallback] if fallback else []) + list(snap.warnings)
    return res


def evaluate(action: dict, snapshot_id: str, *, snapshot: Snapshot | None = None,
             band: float = BAND, use_court: bool = True, court_client=None,
             freeze: bool = True, court_budget_usd: float | None = None) -> Result:
    kind = action.get("type")
    if kind not in ("trade", "waiver", "startsit"):
        raise ValueError(f"unsupported action {kind!r}")
    snap = snapshot if snapshot is not None else load_snapshot(snapshot_id)
    if kind != "trade":
        return _roster_action(action, snap)
    text = action.get("text", "")

    reason = _unsupported(snap, text)
    if reason:
        return Result(Ruling("UNSUPPORTED", reason, band=band), snap)
    deadline = snap.settings.get("trade_deadline")
    if deadline and snap.current_week > int(deadline):
        return Result(Ruling("INVALID", f"the league's trade deadline (week {deadline}) "
                                        "has passed", band=band), snap)
    if int(snap.settings.get("disable_trades") or 0):
        return Result(Ruling("INVALID", "trades are disabled in this league", band=band), snap)
    try:
        trade = trade_from_ids(snap, action["give"], action["get"]) if "give" in action \
            else parse_trade(snap, text)
    except Invalid as e:
        return Result(Ruling("INVALID", str(e), band=band), snap)
    weeks = horizon(snap, trade.give + trade.get)
    if not weeks:  # D10
        return Result(Ruling("INVALID", "season over / no unlocked weeks", band=band), snap)

    matrix, fallback, error = _matrix(snap, weeks[0])
    if error:
        return Result(Ruling("INVALID", band=band), snap, matrix, error=error)

    try:
        ruling = rule(Evaluator(snap, matrix, weeks), trade, band)
    except Invalid as e:
        return Result(Ruling("INVALID", str(e), band=band), snap, matrix)
    if snap.league_stale:
        ruling.notes.append(f"Rosters as of {snap.league_as_of}: Sleeper didn't respond, "
                            "so this uses the last stored copy.")
    if fallback:
        ruling.notes.append(fallback)
    ruling.notes.extend(snap.warnings)
    result = Result(ruling, snap, matrix)
    if use_court:
        result.court = court.argue(snap, matrix, ruling, client=court_client,
                                   budget_usd=court_budget_usd)
        result.evidence = court.bundle(snap, matrix, ruling)
    if freeze:
        result.ledger_key = ledger.freeze(action, snapshot_id, snap.league.get("league_id", ""),
                                          ruling)
    return result

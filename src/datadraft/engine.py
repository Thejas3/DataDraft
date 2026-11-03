"""The one public entry point (D7): evaluate(action, snapshot_id) -> Result.

The CLI (and later the API) builds or names a snapshot and calls this; nothing outside
the engine imports the other modules. Milestone 1 supports the "trade" action."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import court, ledger
from .decide import BAND, Ruling, rule
from .delta import Evaluator, Invalid, horizon, parse_trade
from .lineup import unsupported_slots
from .projections import GuardError, guard, project
from .snapshot import Snapshot, load_snapshot

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


def evaluate(action: dict, snapshot_id: str, *, snapshot: Snapshot | None = None,
             band: float = BAND, use_court: bool = True, court_client=None,
             freeze: bool = True) -> Result:
    if action.get("type") != "trade":
        raise ValueError(f"unsupported action {action.get('type')!r} in Milestone 1")
    snap = snapshot if snapshot is not None else load_snapshot(snapshot_id)
    text = action["text"]

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
        trade = parse_trade(snap, text)
    except Invalid as e:
        return Result(Ruling("INVALID", str(e), band=band), snap)
    weeks = horizon(snap, trade.give + trade.get)
    if not weeks:  # D10
        return Result(Ruling("INVALID", "season over / no unlocked weeks", band=band), snap)

    matrix = project(snap)
    try:
        guard(snap, matrix, weeks[0])
    except GuardError as e:
        return Result(Ruling("INVALID", band=band), snap, matrix,
                      error=f"Projections look wrong today; rulings paused ({e}).")

    try:
        ruling = rule(Evaluator(snap, matrix, weeks), trade, band)
    except Invalid as e:
        return Result(Ruling("INVALID", str(e), band=band), snap, matrix)
    if snap.league_stale:
        ruling.notes.append(f"Rosters as of {snap.league_as_of}: Sleeper didn't respond, "
                            "so this uses the last stored copy.")
    ruling.notes.extend(snap.warnings)
    result = Result(ruling, snap, matrix)
    if use_court:
        result.court = court.argue(snap, matrix, ruling, client=court_client)
    if freeze:
        result.ledger_key = ledger.freeze(action, snapshot_id, snap.league.get("league_id", ""),
                                          ruling)
    return result

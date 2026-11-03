"""The deterministic ruling (§11) and the counteroffer search (§4)."""

from __future__ import annotations

from dataclasses import dataclass, field

from .delta import Evaluator, Invalid, Trade, TradeDelta, roster
from .projections import positions

BAND = 1.0  # pts/week; a configurable prior until calibration exists (phase 2)


@dataclass
class Ruling:
    verdict: str  # ACCEPT | REJECT | TOSS-UP | COUNTER | INVALID | UNSUPPORTED
    reason: str = ""
    delta: TradeDelta | None = None
    counter: TradeDelta | None = None
    band: float = BAND
    notes: list = field(default_factory=list)


def variants(ev: Evaluator, t: Trade):
    """§4 neighbors: add one of their players, drop one of mine, or swap one received
    player for another of theirs at the same position."""
    theirs = sorted(set(roster(ev.snap, t.them).get("players") or []) - set(t.get))
    for p in theirs:
        yield Trade(t.me, t.them, t.give, t.get + (p,))
    if len(t.give) > 1:
        for p in t.give:
            yield Trade(t.me, t.them, tuple(x for x in t.give if x != p), t.get)
    for r in t.get:
        pos = positions(ev.snap.players, r)
        for p in theirs:
            if positions(ev.snap.players, p) & pos:
                yield Trade(t.me, t.them, t.give, tuple(p if x == r else x for x in t.get))


def counteroffer(ev: Evaluator, t: Trade) -> TradeDelta | None:
    best = None
    for v in variants(ev, t):
        try:
            d = ev.trade(v)
        except Invalid:
            continue
        if d.them.delta <= 0:
            continue
        key = (d.me.delta, d.them.delta, tuple(sorted(v.get)), tuple(sorted(v.give)))
        if best is None or key > best[0]:
            best = (key, d)
    return best[1] if best else None


def rule(ev: Evaluator, t: Trade, band: float = BAND) -> Ruling:
    d = ev.trade(t)
    if d.me.delta >= band:
        verdict = "ACCEPT"
        counter = None
    else:
        verdict = "REJECT" if d.me.delta <= -band else "TOSS-UP"
        counter = counteroffer(ev, t)
        if counter and counter.me.delta >= band and counter.them.delta > 0:
            verdict = "COUNTER"
        else:
            counter = None
    r = Ruling(verdict, delta=d, counter=counter, band=band)
    if len(t.give) != len(t.get):
        r.notes.append("Depth-as-insurance not modeled (v1): uneven trades lean toward "
                       "the side consolidating talent.")
    return r


# --- waivers (§8b, D23) ---------------------------------------------------------------

import datetime as _dt  # noqa: E402

from .delta import Side, active, horizon, player_name, week_over  # noqa: E402
from .lineup import SLOT_ELIGIBILITY, Candidate, optimal, starting_slots  # noqa: E402
from .projections import cell, team_weeks  # noqa: E402

POOL = 50  # §8b: at most the top 50 free agents by ROS points (a prefilter only)
NON_NESTED_POOL = 20  # assignment-solver layouts narrow the pool (§8b)
SHOW = 5


@dataclass
class WaiverPick:
    add: str
    drop: str | None  # canonical §3 drop after re-scoring; None if the roster had room
    status: str  # "waivers" | "free agent"
    side: Side
    weeks: tuple

    @property
    def delta(self) -> float:
        return self.side.delta


@dataclass
class Waivers:
    roster_id: int
    picks: list
    considered: int  # free agents that passed the prefilter
    weeks: tuple


def rostered(snap) -> set:
    return {p for r in snap.rosters for p in (r.get("players") or [])}


def recent_drops(snap) -> dict:
    """{player_id: dropped_at (ms)} from this week's and last week's transactions."""
    out = {}
    for t in snap.transactions:
        if t.get("status") != "complete":
            continue
        for pid in (t.get("drops") or {}):
            out[pid] = max(out.get(pid, 0), int(t.get("status_updated") or t.get("created") or 0))
    return out


def _game(snap, pid: str, week: int):
    team = pid if "DEF" in positions(snap.players, pid) else (snap.players.get(pid) or {}).get("team")
    return next((g for g in snap.schedule if int(g.get("week", 0)) == week
                 and team in (g.get("home"), g.get("away"))), None)


def waiver_status(snap, pid: str, drops: dict) -> str:
    """D23: 'waivers' if dropped within the league's waiver_clear_days, or if the player's
    game this week has started (Sleeper locks them until waivers run); else 'free agent'."""
    days = int(snap.settings.get("waiver_clear_days") or 0)
    dropped = drops.get(pid)
    if dropped and days:
        cleared = _dt.datetime.fromtimestamp(dropped / 1000, _dt.UTC).date() + _dt.timedelta(days=days)
        if cleared > snap.today:
            return "waivers"
    g = _game(snap, pid, snap.current_week)
    if g is not None and g.get("status") not in (None, "pre_game"):
        return "waivers"
    return "free agent"


def _eligible(snap, pid: str, slots: list) -> bool:
    pos = positions(snap.players, pid)
    return any(pos & SLOT_ELIGIBILITY.get(s, set()) for s in slots)


def waivers(snap, matrix: dict, rid: int, *, top: int = SHOW) -> Waivers:
    slots = starting_slots(snap.roster_positions)
    start = snap.current_week + (1 if week_over(snap) else 0)
    full = tuple(range(start, snap.last_week() + 1))
    if not full:
        return Waivers(rid, [], 0, full)
    mine = active(snap, rid)
    ros = {p: sum(cell(matrix, w, p).points for w in full)
           for p in set(snap.players) | mine}
    taken = rostered(snap)
    weakest: dict = {}
    for p in mine:
        for pos in positions(snap.players, p):
            weakest[pos] = min(weakest.get(pos, float("inf")), ros[p])
    pool = []
    for p in snap.players:
        info = snap.players[p] or {}
        if p in taken or info.get("injury_status") in ("IR", "PUP") or ros.get(p, 0) <= 0:
            continue
        if not _eligible(snap, p, slots):
            continue
        if any(ros[p] > weakest.get(pos, float("-inf")) for pos in positions(snap.players, p)):
            pool.append(p)
    nested = all(s in ("QB", "RB", "WR", "TE", "K", "DEF", "FLEX", "SUPER_FLEX") for s in slots)
    pool = sorted(pool, key=lambda p: (-ros[p], p))[:POOL if nested else NON_NESTED_POOL]

    drops = recent_drops(snap)
    evaluators: dict = {}

    def ev_for(weeks):
        if weeks not in evaluators:
            evaluators[weeks] = Evaluator(snap, matrix, weeks)
        return evaluators[weeks]

    base = ev_for(full)
    starts = {p: sum(1 for w in full if p in base.week(mine, w)[1]) for p in mine}
    bench = sorted(p for p in mine if starts[p] * 2 < len(full))  # bench for most weeks
    room = len(mine) < base.limit
    best: dict = {}
    for x in pool:
        status = waiver_status(snap, x, drops)
        clears = snap.today + _dt.timedelta(days=1) if status == "waivers" else snap.today
        for d in ([None] if room else []) + bench:
            weeks = horizon(snap, (x,) + ((d,) if d else ()), clears)
            if not weeks:
                continue
            ev = ev_for(weeks)
            after = (mine - {d}) | {x} if d else mine | {x}
            gain = ev.total(after) - ev.total(mine)
            if x not in best or gain > best[x][0] + 1e-9:
                best[x] = (gain, weeks, status)
    ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))[:top]
    picks = []
    for x, (_, weeks, status) in ranked:
        # Canonical §3 re-score: add, then the full forced-drop search picks the drop.
        side = ev_for(weeks).side(rid, mine, mine | {x})
        if side.delta > 0:
            picks.append(WaiverPick(x, side.forced_drops[0] if side.forced_drops else None,
                                    status, side, weeks))
    picks.sort(key=lambda p: (-p.delta, p.add))
    return Waivers(rid, picks, len(pool), full)


# --- start/sit ---------------------------------------------------------------------------

@dataclass
class SlotPick:
    slot: str
    player_id: str | None
    points: float  # actual if locked, else projected
    locked: bool = False
    source: str = ""
    availability: str = ""


@dataclass
class StartSit:
    roster_id: int
    week: int
    slots: list
    start: list  # player_ids to move into the lineup
    sit: list  # player_ids to move out
    gain: float  # projected points over the open slots vs the current lineup
    total: float  # locked actual + open-slot projection
    warnings: list
    live_as_of: str


def is_locked(snap, pid: str, now: float, kickoffs: dict) -> bool:
    """A player is locked once his game this week has kicked off: from the nflverse
    kickoff time when known, else Sleeper's game status."""
    g = _game(snap, pid, snap.current_week)
    if g is None:
        return False
    team = pid if "DEF" in positions(snap.players, pid) else (snap.players.get(pid) or {}).get("team")
    kick = kickoffs.get(team)
    if kick is not None and now >= kick:
        return True
    return g.get("status") not in (None, "pre_game")


def start_sit(snap, matrix: dict, rid: int, live: dict, *, now: float, live_as_of: str,
              kickoffs: dict | None = None, status_as_of: float | None = None) -> StartSit:
    """Optimize only the unlocked slots of this week's lineup. `live` is the current-week
    Sleeper matchup for this roster (starters in slot order, players_points), fetched at
    request time; locked players keep their slot and score their actual points."""
    kickoffs = kickoffs or {}
    week = snap.current_week
    slots = starting_slots(snap.roster_positions)
    current = list(live.get("starters") or roster(snap, rid).get("starters") or [])
    current += ["0"] * (len(slots) - len(current))
    actual = live.get("players_points") or {}
    mine = active(snap, rid)
    picks: list = [None] * len(slots)
    open_idx = []
    for i, (slot, pid) in enumerate(zip(slots, current)):
        if pid and pid != "0" and is_locked(snap, pid, now, kickoffs):
            picks[i] = SlotPick(slot, pid, float(actual.get(pid) or 0.0), True, "actual")
        else:
            open_idx.append(i)
    locked_ids = {p.player_id for p in picks if p}
    free = [p for p in mine if p not in locked_ids and not is_locked(snap, p, now, kickoffs)]
    cands = [Candidate(p, positions(snap.players, p), cell(matrix, week, p).points) for p in free]
    _, chosen = optimal(cands, [slots[i] for i in open_idx])
    by_slot: dict = {}
    for pid, slot in chosen.items():
        by_slot.setdefault(slot, []).append(pid)
    for s in by_slot.values():
        s.sort(key=lambda p: (-cell(matrix, week, p).points, p))
    # Keep a current starter in his own slot when he is still recommended for that type.
    for i in open_idx:
        slot, cur = slots[i], current[i]
        if cur in by_slot.get(slot, []):
            by_slot[slot].remove(cur)
            picks[i] = cur
    for i in open_idx:
        if picks[i] is None:
            queue = by_slot.get(slots[i]) or []
            picks[i] = queue.pop(0) if queue else None
    # Nobody better for a slot: leave the current starter there rather than empty it.
    placed = {p for p in picks if isinstance(p, str)}
    for i in open_idx:
        cur = current[i]
        if picks[i] is None and cur and cur != "0" and cur in mine and cur not in placed:
            picks[i] = cur
            placed.add(cur)
    out = []
    for i, p in enumerate(picks):
        if isinstance(p, SlotPick):
            out.append(p)
            continue
        c = cell(matrix, week, p) if p else None
        out.append(SlotPick(slots[i], p, c.points if c else 0.0, False,
                            c.source if c else "", c.availability if c else ""))
    now_open = {current[i] for i in open_idx if current[i] and current[i] != "0"}
    rec_open = {out[i].player_id for i in open_idx if out[i].player_id}
    start = sorted(rec_open - now_open, key=lambda p: -cell(matrix, week, p).points)
    sit = sorted(now_open - rec_open, key=lambda p: -cell(matrix, week, p).points)
    gain = round(sum(cell(matrix, week, p).points for p in rec_open)
                 - sum(cell(matrix, week, p).points for p in now_open), 2)
    total = round(sum(p.points for p in out), 2)
    warnings = []
    if week_over(snap):
        warnings.append(f"Every week {week} game is final; next week's lineup opens when "
                        "Sleeper rolls the week over.")
    if status_as_of is not None:
        for p in out:
            if p.locked or not p.player_id:
                continue
            team = p.player_id if "DEF" in positions(snap.players, p.player_id) else \
                (snap.players.get(p.player_id) or {}).get("team")
            kick = kickoffs.get(team)
            if kick and 0 <= kick - now <= 24 * 3600 and now - status_as_of > 12 * 3600:
                warnings.append(f"{player_name(snap.players, p.player_id)}: status is over "
                                "12 h old; check inactives before lock.")
    for p in out:
        if p.player_id and not p.locked and not week_over(snap) and week not in team_weeks(snap, (
                p.player_id if "DEF" in positions(snap.players, p.player_id)
                else (snap.players.get(p.player_id) or {}).get("team"))):
            warnings.append(f"{player_name(snap.players, p.player_id)} is on bye.")
    return StartSit(rid, week, out, start, sit, gain, total, warnings, live_as_of)

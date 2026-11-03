"""Trade legality, forced drops (§3) and the rest-of-season lineup delta for both teams.

delta = Σ over horizon weeks of [optimal lineup after − optimal lineup before], reported
as points per week. The horizon starts at the first week the trade can change a lineup
(D17) and ends at the league's final playoff week."""

from __future__ import annotations

import datetime as dt
import itertools
import re
import unicodedata
from dataclasses import dataclass, field

from .lineup import NON_STARTING, Candidate, optimal, starting_slots
from .projections import cell, positions

DEFAULT_REVIEW_DAYS = 1


class Invalid(Exception):
    """The trade can't happen as stated (§3); the reason is shown as an INVALID ruling."""


@dataclass(frozen=True)
class Trade:
    me: int  # roster_id giving `give`
    them: int  # roster_id giving `get`
    give: tuple  # player_ids I send
    get: tuple  # player_ids I receive


@dataclass
class Side:
    roster_id: int
    before: dict  # week -> optimal lineup points
    after: dict
    forced_drops: tuple = ()
    lineup_after: dict = field(default_factory=dict)  # first horizon week {pid: slot}
    lineup_before: dict = field(default_factory=dict)

    @property
    def per_week(self) -> dict:
        return {w: round(self.after[w] - self.before[w], 2) for w in self.before}

    @property
    def delta(self) -> float:
        return round(sum(self.per_week.values()) / len(self.before), 2) if self.before else 0.0


@dataclass
class TradeDelta:
    trade: Trade
    weeks: tuple
    me: Side
    them: Side


# ---- names -------------------------------------------------------------------------

def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'’\-]", "", s)
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return " ".join(s.split())


def player_name(players: dict, pid: str) -> str:
    p = players.get(pid) or {}
    if "DEF" in positions(players, pid):
        return f"{p.get('first_name', pid)} {p.get('last_name', '')} D/ST".strip()
    full = p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
    return full or pid


def _aliases(players: dict, pid: str) -> set:
    p = players.get(pid) or {}
    names = {_norm(player_name(players, pid)), pid.lower()}
    if "DEF" in positions(players, pid):
        names |= {pid.lower(), _norm(f"{p.get('first_name', '')} {p.get('last_name', '')}"),
                  _norm(p.get("last_name", "")), _norm(f"{pid} dst"), _norm(f"{pid} def")}
    return {n for n in names if n}


def resolve(snap, name: str) -> str:
    """Map a typed name to a rostered player_id. Only rostered players are searched, so
    common names rarely collide; when they do, the error lists the choices."""
    key = _norm(name)
    hits = []
    for r in snap.rosters:
        for pid in r.get("players") or []:
            if key in _aliases(snap.players, pid):
                hits.append(pid)
    if not hits:  # allow a unique last-name or prefix match as a convenience
        for r in snap.rosters:
            for pid in r.get("players") or []:
                full = _norm(player_name(snap.players, pid))
                if full.endswith(" " + key) or full.startswith(key + " "):
                    hits.append(pid)
    hits = sorted(set(hits))
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise Invalid(f"'{name}' isn't on any roster in this league")
    choices = ", ".join(player_name(snap.players, h) for h in hits)
    raise Invalid(f"'{name}' matches more than one rostered player: {choices}")


def owner_of(snap, pid: str) -> int:
    for r in snap.rosters:
        if pid in (r.get("players") or []):
            return int(r["roster_id"])
    raise Invalid(f"{player_name(snap.players, pid)} isn't on any roster in this league")


def parse_trade(snap, text: str) -> Trade:
    """'A, B for C': I send A and B, and receive C."""
    parts = re.split(r"\s+for\s+", text.strip(), flags=re.I)
    if len(parts) != 2:
        raise Invalid("write the trade as 'A, B for C' (what you send, then what you get)")
    give = tuple(resolve(snap, n) for n in parts[0].split(",") if n.strip())
    get = tuple(resolve(snap, n) for n in parts[1].split(",") if n.strip())
    if not give or not get:
        raise Invalid("both sides of the trade need at least one player")
    mine = {owner_of(snap, p) for p in give}
    theirs = {owner_of(snap, p) for p in get}
    if len(mine) != 1:
        raise Invalid("everything you send has to come from one roster")
    if len(theirs) != 1:
        raise Invalid("everything you receive has to come from one roster")
    if mine == theirs:
        raise Invalid("both sides of the trade are on the same roster")
    return Trade(mine.pop(), theirs.pop(), give, get)


# ---- horizon (D17) -----------------------------------------------------------------

def _team(snap, pid: str) -> str | None:
    if "DEF" in positions(snap.players, pid):
        return pid
    return (snap.players.get(pid) or {}).get("team")


def first_week(snap, involved: tuple) -> int:
    """The current week counts only if the trade clears review before every involved
    player's game this week. Otherwise the horizon starts next week."""
    review = snap.settings.get("trade_review_days")
    review = DEFAULT_REVIEW_DAYS if review is None else int(review)
    clears = snap.today + dt.timedelta(days=review)
    week = snap.current_week
    games = {}
    for g in snap.schedule:
        if int(g.get("week", 0)) == week:
            games[g.get("home")] = g
            games[g.get("away")] = g
    for pid in involved:
        g = games.get(_team(snap, pid))
        if g is None:
            continue  # bye: nothing to lock
        date = dt.date.fromisoformat(g["date"])
        if g.get("status") != "pre_game" or date < clears or (review and date == clears):
            return week + 1
    return week


def horizon(snap, involved: tuple) -> tuple:
    return tuple(range(first_week(snap, involved), snap.last_week() + 1))


# ---- lineup math -------------------------------------------------------------------

def active_limit(snap) -> int:
    return len([s for s in snap.roster_positions if s not in ("IR", "TAXI")])


def roster(snap, rid: int) -> dict:
    for r in snap.rosters:
        if int(r["roster_id"]) == rid:
            return r
    raise Invalid(f"roster {rid} isn't in this league")


def active(snap, rid: int) -> frozenset:
    r = roster(snap, rid)
    held = set(r.get("reserve") or []) | set(r.get("taxi") or [])
    return frozenset(p for p in (r.get("players") or []) if p not in held)


class Evaluator:
    """Optimal-lineup totals over a fixed horizon, cached per (roster, week) so the
    counteroffer search can re-run delta many times cheaply."""

    def __init__(self, snap, matrix: dict, weeks: tuple):
        self.snap, self.matrix, self.weeks = snap, matrix, weeks
        self.slots = starting_slots(snap.roster_positions)
        self.limit = active_limit(snap)
        self._cache: dict = {}

    def week(self, players: frozenset, week: int) -> tuple[float, dict]:
        key = (players, week)
        if key not in self._cache:
            cands = [Candidate(p, positions(self.snap.players, p),
                               cell(self.matrix, week, p).points) for p in sorted(players)]
            self._cache[key] = optimal(cands, self.slots)
        return self._cache[key]

    def by_week(self, players: frozenset) -> dict:
        return {w: round(self.week(players, w)[0], 2) for w in self.weeks}

    def total(self, players: frozenset) -> float:
        return sum(self.week(players, w)[0] for w in self.weeks)

    def settle(self, before: frozenset, after: frozenset) -> tuple[frozenset, tuple]:
        """Apply §3 forced drops: over the active limit, drop whichever players cost
        this side the least ROS points, searching every droppable combination."""
        excess = len(after) - max(self.limit, len(before))
        if excess <= 0:
            return after, ()
        best = None
        for drop in itertools.combinations(sorted(after), excess):
            kept = after - set(drop)
            value = self.total(kept)
            if best is None or value > best[0] + 1e-9:
                best = (value, kept, drop)
        return best[1], best[2]

    def side(self, rid: int, before: frozenset, after: frozenset) -> Side:
        after, drops = self.settle(before, after)
        w0 = self.weeks[0]
        return Side(rid, self.by_week(before), self.by_week(after), drops,
                    self.week(after, w0)[1], self.week(before, w0)[1])

    def trade(self, t: Trade) -> TradeDelta:
        mine, theirs = active(self.snap, t.me), active(self.snap, t.them)
        held = {p for rid in (t.me, t.them) for p in
                (set(roster(self.snap, rid).get("players") or []))}
        for p in t.give + t.get:
            if p not in held:
                raise Invalid(f"{player_name(self.snap.players, p)} isn't on either roster")
        r_me, r_them = roster(self.snap, t.me), roster(self.snap, t.them)
        give, get = set(t.give), set(t.get)
        if not give <= set(r_me.get("players") or []):
            raise Invalid("something you send isn't on your roster")
        if not get <= set(r_them.get("players") or []):
            raise Invalid("something you receive isn't on their roster")
        # Traded players arrive on the active roster, wherever they sat before.
        me_after = (mine - give) | get
        them_after = (theirs - get) | give
        return TradeDelta(t, self.weeks, self.side(t.me, mine, frozenset(me_after)),
                          self.side(t.them, theirs, frozenset(them_after)))

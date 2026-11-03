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

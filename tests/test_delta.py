import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from conftest import synthetic
from datadraft.decide import rule
from datadraft.delta import Evaluator, Invalid, Trade, horizon, parse_trade
from datadraft.projections import project

A = ["QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "WR3"]
B = ["QB2", "RB3", "RB4", "WR4", "WR5", "TE2", "RB5"]
PTS = {"QB1": 20, "RB1": 15, "RB2": 10, "WR1": 14, "WR2": 12, "TE1": 8, "WR3": 9,
       "QB2": 19, "RB3": 16, "RB4": 6, "WR4": 13, "WR5": 11, "TE2": 9, "RB5": 7}


def ev_for(snap, t):
    return Evaluator(snap, project(snap), horizon(snap, t.give + t.get))


def test_parse_trade_infers_both_rosters():
    snap = synthetic({1: A, 2: B}, PTS)
    t = parse_trade(snap, "wr3 player, te1 player for RB3 Player")
    assert (t.me, t.them, t.give, t.get) == (1, 2, ("WR3", "TE1"), ("RB3",))


@pytest.mark.parametrize("text,msg", [
    ("Nobody Here for RB3 Player", "isn't on any roster"),
    ("WR3 Player for RB1 Player", "same roster"),
    ("WR3 Player, RB3 Player for TE2 Player", "one roster"),
    ("WR3 Player", "A, B for C"),
])
def test_parse_trade_rejects_bad_input(text, msg):
    with pytest.raises(Invalid, match=msg):
        parse_trade(synthetic({1: A, 2: B}, PTS), text)


def test_one_for_one_delta_is_lineup_change():
    snap = synthetic({1: A, 2: B}, PTS)
    t = parse_trade(snap, "WR3 Player for RB4 Player")
    d = ev_for(snap, t).trade(t)
    # WR3 (9) was my FLEX and RB4 (6) replaces him there; RB4 was their FLEX and WR3
    # replaces him there.
    assert d.me.delta == -3.0 and d.them.delta == 3.0
    assert d.me.per_week == {9: -3.0, 10: -3.0}


def test_forced_drop_minimizes_own_loss():
    full = A + ["BN1", "BN2", "BN3"]  # 10 players: exactly the active limit
    pts = {**PTS, "BN1": 1, "BN2": 2, "BN3": 3}
    snap = synthetic({1: full, 2: B}, pts, positions={"BN1": "RB", "BN2": "RB", "BN3": "RB"})
    t = parse_trade(snap, "TE1 Player for TE2 Player, RB5 Player")
    d = ev_for(snap, t).trade(t)
    assert d.me.forced_drops == ("BN1",)


def test_identical_swap_is_zero():
    snap = synthetic({1: A, 2: B}, {**PTS, "RB4": 15})
    t = parse_trade(snap, "RB1 Player for RB4 Player")
    d = ev_for(snap, t).trade(t)
    assert d.me.delta == 0 and d.them.delta == 0


def test_horizon_starts_this_week_when_trade_clears_before_kickoff():
    snap = synthetic({1: A, 2: B}, PTS)  # games are 5 days out, no review period
    assert horizon(snap, ("WR3",)) == (9, 10)


def test_horizon_skips_week_when_game_started():
    sched = [{"week": 9, "home": "AAA", "away": "BBB", "status": "in_game", "date": "2026-11-03"},
             {"week": 10, "home": "AAA", "away": "BBB", "status": "pre_game", "date": "2026-11-10"}]
    snap = synthetic({1: A, 2: B}, PTS, schedule=sched)
    assert horizon(snap, ("WR3",)) == (10,)


def test_horizon_skips_week_when_review_outlasts_kickoff():
    snap = synthetic({1: A, 2: B}, PTS, settings={"trade_review_days": 5})
    assert horizon(snap, ("WR3",)) == (10,)


def test_ruling_bands_and_counter():
    snap = synthetic({1: A, 2: B}, PTS)
    accept = parse_trade(snap, "RB2 Player for RB3 Player")  # +6 for me
    assert rule(ev_for(snap, accept), accept).verdict == "ACCEPT"
    reject = parse_trade(snap, "RB1 Player for RB4 Player")  # -6 for me (RB4 replaces RB1)
    r = rule(ev_for(snap, reject), reject)
    assert r.verdict in {"REJECT", "COUNTER"}
    if r.counter:
        assert r.counter.me.delta >= 1.0 and r.counter.them.delta > 0


team = st.lists(st.integers(min_value=0, max_value=30), min_size=7, max_size=7)


@settings(max_examples=150, deadline=None)
@given(team, team)
def test_upgrade_at_same_position_never_hurts(pa, pb):
    """Property: a 1-for-1 swap for a same-position player projected at least as high
    can't lower my lineup, and can't raise theirs."""
    pts = dict(zip(A, pa)) | dict(zip(B, pb))
    assume(pts["WR4"] >= pts["WR3"])
    snap = synthetic({1: A, 2: B}, pts)
    d = Evaluator(snap, project(snap), (9, 10)).trade(Trade(1, 2, ("WR3",), ("WR4",)))
    assert d.me.delta >= 0 and d.them.delta <= 0

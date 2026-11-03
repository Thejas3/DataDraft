"""Waivers (§8b, D23) and start/sit (live locks, open-slot optimization)."""

import time

from conftest import replace, synthetic
from datadraft.cli import render_startsit, render_waivers
from datadraft.engine import evaluate

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN", "BN"]
MINE = ["QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "WR3", "RB5", "WR6", "TE3"]  # full: 10
THEIRS = ["QB2", "RB3", "RB4", "WR4", "WR5", "TE2"]
PTS = {"QB1": 20, "RB1": 15, "RB2": 10, "WR1": 14, "WR2": 12, "TE1": 8, "WR3": 9,
       "RB5": 3, "WR6": 2, "TE3": 1, "QB2": 19, "RB3": 16, "RB4": 6, "WR4": 13, "WR5": 11,
       "TE2": 9}


def with_free_agents(snap, fas: dict, status=None, team="AAA"):
    players = dict(snap.players)
    projections = {w: list(rows) for w, rows in snap.projections.items()}
    for pid, pts in fas.items():
        pos = pid.rstrip("0123456789")
        players[pid] = {"full_name": f"{pid} Player", "last_name": "Player", "position": pos,
                        "fantasy_positions": [pos], "team": team,
                        "injury_status": (status or {}).get(pid)}
        for w in projections:
            projections[w].append({"player_id": pid, "week": w, "stats": {
                "pts": pts, "pass_yd": 0, "rush_yd": 0, "rec_yd": 0, "rec": 0}})
    return replace(snap, players=players, projections=projections)


def league(fas=None, **kw):
    snap = synthetic({1: MINE, 2: THEIRS}, PTS, slots=SLOTS, **kw)
    return with_free_agents(snap, fas or {})


def run_waivers(snap, rid=1):
    return evaluate({"type": "waiver", "roster_id": rid}, snap.snapshot_id, snapshot=snap)


def test_best_add_drops_the_cheapest_bench_player():
    w = run_waivers(league({"RB9": 12, "WR9": 4})).waivers
    top = w.picks[0]
    assert (top.add, top.drop, top.status) == ("RB9", "TE3", "free agent")
    # RB9 (12) takes an RB slot and RB2 (10) moves to FLEX over WR3 (9): +3.0 a week.
    assert top.delta == 3.0
    assert [p.add for p in w.picks] == ["RB9"]  # WR9 never makes the lineup


def test_open_roster_spot_needs_no_drop():
    snap = synthetic({1: MINE[:9], 2: THEIRS}, PTS, slots=SLOTS)
    pick = run_waivers(with_free_agents(snap, {"RB9": 12})).waivers.picks[0]
    assert pick.drop is None


def test_ir_free_agents_and_worse_players_are_skipped():
    w = run_waivers(league({"RB9": 30, "TE9": 0.5}, )).waivers
    assert w.considered == 1
    snap = with_free_agents(synthetic({1: MINE, 2: THEIRS}, PTS, slots=SLOTS), {"RB9": 30},
                            status={"RB9": "IR"})
    assert run_waivers(snap).waivers.picks == []


def test_recent_drop_and_started_game_put_a_player_on_waivers():
    snap = replace(league({"RB9": 12}), league=dict(
        league({"RB9": 12}).league,
        settings={**league().settings, "waiver_clear_days": 2}),
        transactions=[{"status": "complete", "drops": {"RB9": 2},
                       "status_updated": 1793606400000}])  # 2026-11-02
    pick = run_waivers(snap).waivers.picks[0]
    assert pick.status == "waivers"
    assert "best add if you win the claim" in render_waivers(run_waivers(snap))
    started = [dict(g, status="in_game") if g["week"] == 9 else g for g in league().schedule]
    snap2 = replace(league({"RB9": 12}), schedule=started)
    pick2 = run_waivers(snap2).waivers.picks[0]
    assert pick2.status == "waivers" and pick2.weeks[0] == 10  # this week is locked


def test_no_upgrade_says_so():
    out = render_waivers(run_waivers(league({"WR9": 1})))
    assert "No free agent beats your bench right now" in out


def test_waivers_meet_the_5_second_target_for_a_12_team_league():
    rosters, pts = {}, {}
    for t in range(12):
        ids = [f"QB{t}a", f"RB{t}a", f"RB{t}b", f"RB{t}c", f"WR{t}a", f"WR{t}b", f"WR{t}c",
               f"WR{t}d", f"TE{t}a", f"TE{t}b"]
        rosters[t + 1] = ids
        pts |= {p: 5 + (hash(p) % 15) for p in ids}
    snap = synthetic(rosters, pts, slots=SLOTS, weeks=tuple(range(9, 18)))
    fas = {f"{pos}9{i}": 4 + (i % 14) for i in range(80) for pos in ("RB", "WR")}
    snap = with_free_agents(snap, fas)
    t0 = time.perf_counter()
    w = run_waivers(snap).waivers
    assert time.perf_counter() - t0 < 5.0
    assert w.considered <= 50 and len(w.picks) <= 5


def test_dynasty_waivers_are_unsupported():
    snap = league({"RB9": 12}, settings={"type": 2})
    res = run_waivers(snap)
    assert res.waivers is None and "dynasty" in res.error


# --- start/sit -------------------------------------------------------------------------

def startsit(snap, starters, points=None, now=None):
    live = {"roster_id": 1, "starters": starters, "players_points": points or {}}
    return evaluate({"type": "startsit", "roster_id": 1, "live": live,
                     "live_as_of": "2026-11-08T18:00Z", "now": now or time.time()},
                    snap.snapshot_id, snapshot=snap).startsit


CURRENT = ["QB1", "RB1", "RB5", "WR1", "WR2", "TE1", "WR3"]  # RB5 (3) starts over RB2 (10)


def test_startsit_swaps_in_the_better_bench_player():
    s = startsit(league(), CURRENT)
    assert (s.start, s.sit, s.gain) == (["RB2"], ["RB5"], 7.0)
    assert s.slots[2].player_id == "RB2" and s.slots[0].player_id == "QB1"


def test_locked_players_keep_their_slot_and_actual_points():
    snap = league()
    # RB5 and RB2 play in a game that has already kicked off.
    players = dict(snap.players, RB5=dict(snap.players["RB5"], team="CCC"),
                   RB2=dict(snap.players["RB2"], team="CCC"))
    sched = snap.schedule + [{"week": 9, "home": "CCC", "away": "DDD", "status": "in_game",
                              "date": "2026-11-08"}]
    snap = replace(snap, players=players, schedule=sched)
    s = startsit(snap, CURRENT, points={"RB5": 11.5})
    assert (s.slots[2].player_id, s.slots[2].locked, s.slots[2].points) == ("RB5", True, 11.5)
    assert "RB2" not in {p.player_id for p in s.slots}  # locked on the bench: can't move in
    assert "LOCKED" in render_startsit(evaluate(
        {"type": "startsit", "roster_id": 1, "live": {"roster_id": 1, "starters": CURRENT,
                                                       "players_points": {"RB5": 11.5}},
         "live_as_of": "x", "now": time.time()}, snap.snapshot_id, snapshot=snap))


def test_best_lineup_already_set():
    best = ["QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "WR3"]
    s = startsit(league(), best)
    assert (s.start, s.sit, s.gain) == ([], [], 0.0)


def test_old_status_near_kickoff_warns_to_check_inactives():
    import polars as pl

    snap = league()
    sched = pl.DataFrame({"week": [9], "gameday": ["2026-11-08"], "gametime": ["13:00"],
                          "home_team": ["AAA"], "away_team": ["BBB"]})
    snap = replace(snap, nflverse={**snap.nflverse, "schedules": sched},
                   build_as_of="2026-11-07T08:00Z")
    kick = 1794160800  # 2026-11-08 13:00 ET
    s = startsit(snap, CURRENT, now=kick - 3 * 3600)
    assert any("check inactives before lock" in w for w in s.warnings)
    fresh = replace(snap, build_as_of="2026-11-08T08:00Z")
    assert not startsit(fresh, CURRENT, now=kick - 3 * 3600).warnings


def test_bye_starter_stays_when_nobody_can_replace_him():
    snap = league()
    players = {p: (dict(v, team="CCC") if p != "TE1" else v) for p, v in snap.players.items()}
    sched = [dict(g, status="complete") for g in snap.schedule if g["week"] == 9]
    sched = [{"week": 9, "home": "CCC", "away": "DDD", "status": "complete",
              "date": "2026-11-08"}] + [g for g in snap.schedule if g["week"] != 9]
    snap = replace(snap, players=players, schedule=sched)  # TE1 (team AAA) is on bye
    s = startsit(snap, CURRENT)
    assert s.slots[5].player_id == "TE1" and s.sit == []
    assert any("is final" in w for w in s.warnings)


def test_waivers_skip_a_finished_week():
    snap = league({"RB9": 12})
    done = [dict(g, status="complete") if g["week"] == 9 else g for g in snap.schedule]
    w = run_waivers(replace(snap, schedule=done)).waivers
    assert w.weeks == (10,) and w.picks[0].weeks == (10,)

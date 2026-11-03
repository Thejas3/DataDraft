"""§1 baseline and §5 availability, on a small synthetic league with nflverse tables."""

import polars as pl
import pytest

from conftest import nfl_frames, replace, synthetic
from datadraft.engine import evaluate
from datadraft.projections import (Availability, body_category, def_line, injury_k, project)

# Sleeper projects WR1 only; WR9 has no Sleeper row, so the baseline must cover it.
ROSTERS = {1: ["QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "WR9"],
           2: ["QB2", "RB3", "RB4", "WR4", "WR5", "TE2", "RB5"]}
SLEEPER = {p: 10 for ps in ROSTERS.values() for p in ps if p != "WR9"}
SCORING = {"rec": 1.0, "rec_yd": 0.1, "pts": 1.0}


def world(*, status=None, extra=None, weeks=(9, 10, 11, 12), current=9, schedule=None,
          scoring=SCORING, **frames):
    snap = synthetic(ROSTERS, SLEEPER, weeks=weeks, current=current, status=status,
                     schedule=schedule)
    league = dict(snap.league, scoring_settings=scoring)
    players = {p: dict(v, **((extra or {}).get(p, {}))) for p, v in snap.players.items()}
    xwalk = {p: (f"G-{p}", "gsis") for p in players}
    return replace(snap, league=league, players=players, nflverse=nfl_frames(**frames),
                   xwalk=xwalk)


def wr9_games(weeks):
    # receptions_exp 4/game, rec_yards_gained_exp 50/game -> 4 + 5 = 9 pts/game
    return [("G-WR9", w, {"receptions_exp": 4.0, "rec_yards_gained_exp": 50.0}) for w in weeks]


def test_baseline_fills_cells_sleeper_did_not_publish():
    snap = world(opportunity=wr9_games(range(1, 9)))
    m = project(snap)
    c = m[9]["WR9"]
    assert (c.source, c.points) == ("baseline", 9.0)
    assert m[9]["WR1"].source == "sleeper"


def test_blend_is_half_trailing_four_half_season():
    games = [("G-WR9", w, {"receptions_exp": r}) for w, r in
             zip(range(1, 9), [0, 0, 0, 0, 8, 8, 8, 8])]
    snap = world(opportunity=games)
    # trailing 4 = 8/game, season = 4/game -> 6.0
    assert project(snap)[9]["WR9"].points == 6.0


def test_baseline_ignores_games_from_the_current_week_on():
    snap = world(opportunity=wr9_games(range(1, 9)) + [("G-WR9", 9, {"receptions_exp": 40.0})])
    assert project(snap)[9]["WR9"].points == 9.0


def test_bye_week_is_zero_for_baseline_cells():
    sched = [{"week": w, "home": "AAA", "away": "BBB", "status": "pre_game",
              "date": f"2026-11-{4 + 7 * (w - 9):02d}"} for w in (9, 11, 12)]
    snap = world(opportunity=wr9_games(range(1, 9)), schedule=sched)
    m = project(snap)
    assert (m[10]["WR9"].points, m[10]["WR9"].availability) == (0.0, "bye")
    assert m[11]["WR9"].points == 9.0


def test_approx_scoring_flag_for_keys_the_baseline_cannot_produce():
    snap = world(opportunity=wr9_games(range(1, 9)), scoring={**SCORING, "bonus_rec_yd_100": 3})
    assert project(snap)[9]["WR9"].approx
    assert not project(world(opportunity=wr9_games(range(1, 9))))[9]["WR9"].approx


def test_te_premium_comes_from_receptions():
    snap = world(opportunity=[("G-TE1", w, {"receptions_exp": 5.0}) for w in range(1, 9)],
                 scoring={"rec": 1.0, "bonus_rec_te": 0.5})
    snap = replace(snap, projections={w: [r for r in rows if r["player_id"] != "TE1"]
                                      for w, rows in snap.projections.items()})
    assert project(snap)[9]["TE1"].points == 7.5


def test_questionable_discounts_baseline_cells_but_not_sleeper_cells():
    snap = world(status={"WR9": "Questionable", "WR1": "Questionable"},
                 opportunity=wr9_games(range(1, 9)))
    m = project(snap)
    assert m[9]["WR9"].points == round(9.0 * 0.85, 2)
    assert m[10]["WR9"].points == 9.0  # future weeks are 1.0
    assert (m[9]["WR1"].points, m[9]["WR1"].availability) == (10.0, "")


def test_late_designation_does_discount_a_sleeper_cell():
    snap = world(status={"WR1": "Doubtful"}, extra={"WR1": {"status_since": "2026-11-02"}})
    old = 1793000000000  # 2026-10-26, before the designation
    snap = replace(snap, projections={w: [dict(r, last_modified=old) for r in rows]
                                      for w, rows in snap.projections.items()})
    c = project(snap)[9]["WR1"]
    assert (c.points, c.availability) == (2.5, "Doubtful: x0.25 (late designation)")


def test_out_extends_for_k_games_by_body_part():
    snap = world(status={"WR1": "Out"}, extra={"WR1": {"injury_body_part": "Right Hamstring"}},
                 injury_k=[("OUT", "hamstring", 40, 2), ("OUT", "*", 900, 1)])
    m = project(snap)
    assert [m[w]["WR1"].points for w in (9, 10, 11)] == [0.0, 0.0, 10.0]
    a = Availability(snap).absence("WR1")
    assert a.note == "typical return: week 11, based on 40 similar injuries since 2015, estimate"


def test_out_with_few_cases_falls_back_to_body_part_median():
    snap = world(status={"WR1": "Out"}, extra={"WR1": {"injury_body_part": "Knee"}},
                 injury_k=[("OUT", "knee", 5, 4), ("ALL", "knee", 60, 3), ("OUT", "*", 900, 1)])
    assert Availability(snap).absence("WR1").k == 3


def test_ir_zero_for_remaining_minimum_since_placement():
    # Placed on IR before week 8 (archived), so weeks 8 is served: 3 more games of the 4.
    sched = [{"week": w, "home": "AAA", "away": "BBB", "status": "pre_game",
              "date": f"2026-{10 if w < 9 else 11}-{[0, 0, 0, 0, 0, 0, 0, 0, 28][w] if w < 9 else 4 + 7 * (w - 9):02d}"}
             for w in (8, 9, 10, 11, 12)]
    snap = world(status={"WR1": "IR"}, extra={"WR1": {"status_since": "2026-10-27"}},
                 schedule=sched, weeks=(9, 10, 11, 12), injury_k=[("IR", "*", 900, 1)])
    m = project(snap)
    assert [m[w]["WR1"].points for w in (9, 10, 11, 12)] == [0.0, 0.0, 0.0, 10.0]


def test_ir_with_unknown_placement_is_treated_as_this_week():
    snap = world(status={"WR1": "IR"}, injury_k=[("IR", "*", 900, 1)])
    a = Availability(snap).absence("WR1")
    assert len(a.weeks) == 4 and "treated as this week" in a.note


def test_def_line_uses_league_tiers():
    line = def_line({"own": {"def_sacks": 3, "def_interceptions": 1},
                     "opp": {"passing_yards": 250, "sack_yards_lost": 20, "rushing_yards": 90},
                     "allowed": 17})
    assert line["pts_allow_14_20"] == 1.0 and line["yds_allow_300_349"] == 1.0
    assert (line["sack"], line["int"], line["yds_allow"]) == (3, 1, 320)


def test_def_trailing_average_scored_with_full_settings():
    games = [(f"g{w}", w, "AAA", "BBB", 10, 24, {"AAA": {"def_sacks": 2}}) for w in range(5, 9)]
    snap = world(team_games=games, scoring={"sack": 1.0, "pts_allow_21_27": -1.0,
                                            "pts_allow_7_13": 3.0})
    rosters = [dict(r, players=r["players"] + ["AAA"]) if r["roster_id"] == 1 else r
               for r in snap.rosters]
    players = dict(snap.players, AAA={"position": "DEF", "fantasy_positions": ["DEF"],
                                      "team": "AAA", "last_name": "Defense"})
    snap = replace(snap, rosters=rosters, players=players,
                   xwalk=dict(snap.xwalk, AAA=("AAA", "team")))
    m = project(snap)
    # AAA allowed 24 every game (home 10, away 24): 2 sacks - 1 = 1.0 per game
    assert (m[9]["AAA"].source, m[9]["AAA"].points) == ("trailing", 1.0)


def test_kicker_trailing_average_by_gsis():
    games = [("G-K1", w, {"fg_made_40_49": 1, "pat_made": 3}) for w in range(5, 9)]
    snap = world(player_stats=games, scoring={"fgm_40_49": 4.0, "xpm": 1.0})
    players = dict(snap.players, K1={"position": "K", "fantasy_positions": ["K"],
                                     "team": "AAA", "last_name": "Kicker"})
    snap = replace(snap, players=players, xwalk=dict(snap.xwalk, K1=("G-K1", "gsis")))
    assert project(snap)[9]["K1"].points == 7.0


def test_guard_failure_uses_baseline_for_every_cell():
    games = [("G-" + p, w, {"receptions_exp": 1.0}) for p in SLEEPER for w in range(1, 9)]
    snap = world(opportunity=games + wr9_games(range(1, 9)))
    starters = [{"roster_id": rid, "starters": ps[:6]} for rid, ps in ROSTERS.items()]
    blank = {w: [dict(r, stats={k: 0 for k in r["stats"]}) for r in rows]
             for w, rows in snap.projections.items()}
    snap = replace(snap, projections=blank, matchups=starters)
    res = evaluate({"type": "trade", "text": "WR9 Player for RB5 Player"}, snap.snapshot_id,
                   snapshot=snap, use_court=False, freeze=False)
    assert not res.error
    assert any("nflverse baseline" in n for n in res.ruling.notes)
    assert {c.source for c in res.matrix[9].values()} == {"baseline"}


@pytest.mark.parametrize("text,cat", [("Left Knee, Ankle", "knee"), (None, "unknown"),
                                      ("Hamstring/Groin", "hamstring"), ("RT Ankle", "ankle"),
                                      ("Knee - PCL", "knee"), ("Foot (Lisfranc)", "foot")])
def test_body_category(text, cat):
    assert body_category(text) == cat


def test_injury_k_counts_consecutive_missed_games_and_designations():
    inj = pl.DataFrame({"season": [2020] * 3, "week": [2, 6, 6], "game_type": ["REG"] * 3,
                        "gsis_id": ["a", "b", "c"], "position": ["WR", "RB", "TE"],
                        "report_status": ["Out", "Out", None],
                        "report_primary_injury": ["Ankle", "Knee", "Knee"]})
    # a: Out wk2 then back wk3 (1 game). b: Out 6, INA 7, bye, RES 9 -> 3 games.
    # c: RES from wk 7 to 9 -> IR case of 3 games, body part from the wk-6 report.
    rows = [("a", 1, "ACT"), ("a", 2, "INA"), ("a", 3, "ACT"),
            ("b", 5, "ACT"), ("b", 6, "INA"), ("b", 7, "INA"), ("b", 9, "RES"), ("b", 10, "ACT"),
            ("c", 6, "ACT"), ("c", 7, "RES"), ("c", 8, "RES"), ("c", 9, "RES"), ("c", 10, "ACT")]
    rw = pl.DataFrame({"season": [2020] * len(rows), "week": [w for _, w, _ in rows],
                       "game_type": ["REG"] * len(rows), "gsis_id": [g for g, _, _ in rows],
                       "position": ["WR"] * len(rows), "status": [s for _, _, s in rows]})
    k = {(d, c): (n, v) for d, c, n, v, _ in injury_k(inj, rw, 2015).iter_rows()}
    assert k[("OUT", "ankle")] == (1, 1)
    assert k[("OUT", "knee")] == (1, 3)
    assert k[("IR", "knee")] == (1, 3)
    assert k[("ALL", "knee")] == (2, 3)
    assert k[("OUT", "*")] == (2, 2)


def test_backtest_scores_both_sources_against_actuals():
    from types import SimpleNamespace

    from datadraft.backtest import compare, render

    snap = world(opportunity=wr9_games(range(1, 9)), current=10, weeks=(10, 11, 12))
    actual = [{"player_id": "WR9", "stats": {"gp": 1, "rec": 5, "rec_yd": 60}},  # 11 pts
              {"player_id": "WR1", "stats": {"gp": 1, "rec": 2, "rec_yd": 20}},  # 4 pts
              {"player_id": "WR2", "stats": {"rec": 9}}]  # didn't play: excluded
    proj = [{"player_id": "WR1", "stats": {"rec": 3, "rec_yd": 30}},  # 6 pts
            {"player_id": "WR9", "stats": {"rec": 4, "rec_yd": 40}}]  # 8 pts

    class Client:
        def stats(self, season, week):
            return SimpleNamespace(data=actual)

        def projections(self, season, week):
            return SimpleNamespace(data=proj)

    rep = compare(snap, Client(), [9])
    s, b = rep.by_source[("sleeper", "WR")], rep.by_source[("baseline", "WR")]
    assert (s.n, round(s.mae, 2), round(s.bias, 2)) == (2, 2.5, -0.5)  # +2, -3
    assert (b.n, round(b.mae, 2)) == (1, 2.0)  # WR9 baseline 9 vs 11
    assert rep.both["sleeper"].n == 1 and "Mean abs error" in render(rep)

from hypothesis import given, settings
from hypothesis import strategies as st

from datadraft.lineup import Candidate, _exact, _greedy, hungarian, optimal, starting_slots
from datadraft.scoring import score

POS = ["QB", "RB", "WR", "TE", "K", "DEF"]
NESTED = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "DEF", "BN", "BN"]


def test_score_is_dot_product_over_league_keys():
    stats = {"pass_yd": 250, "pass_td": 2, "rec": 3, "pts_ppr": 99, "gp": 1}
    assert score(stats, {"pass_yd": 0.04, "pass_td": 4, "rec": 1}) == 10 + 8 + 3


def test_greedy_fills_flex_with_best_leftover():
    c = [Candidate("rb1", frozenset({"RB"}), 20), Candidate("rb2", frozenset({"RB"}), 15),
         Candidate("rb3", frozenset({"RB"}), 12), Candidate("wr1", frozenset({"WR"}), 10)]
    total, lineup = optimal(c, ["RB", "RB", "WR", "FLEX"])
    assert total == 57 and lineup["rb3"] == "FLEX"


def test_empty_slot_when_no_eligible_player():
    total, lineup = optimal([Candidate("qb", frozenset({"QB"}), 18)], ["QB", "TE"])
    assert total == 18 and lineup == {"qb": "QB"}


def test_hungarian_small():
    assert hungarian([[4, 1, 3], [2, 0, 5], [3, 2, 2]]) == [1, 0, 2]


rosters = st.lists(
    st.tuples(st.sampled_from(POS), st.floats(min_value=0, max_value=40, allow_nan=False)),
    min_size=0, max_size=18)


@settings(max_examples=300, deadline=None)
@given(rosters)
def test_greedy_matches_exact_on_nested_slots(players):
    """§10: on nested layouts the greedy fill is exactly optimal."""
    cands = [Candidate(f"p{i}", frozenset({pos}), round(pts, 2)) for i, (pos, pts) in enumerate(players)]
    slots = starting_slots(NESTED)
    g, _ = _greedy(cands, slots)
    e, _ = _exact(cands, slots)
    assert abs(g - e) < 1e-6

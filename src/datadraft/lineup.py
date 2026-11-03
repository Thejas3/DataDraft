"""Exact optimal starting lineup for one week (§10).

Standard Sleeper slots nest (position ⊂ FLEX ⊂ SUPER_FLEX), so filling dedicated slots
greedily, then FLEX, then SUPER_FLEX is exactly optimal when every player has a single
fantasy position. Anything else (WRRB_FLEX, REC_FLEX, multi-position players) goes to an
exact assignment solver (Hungarian algorithm)."""

from __future__ import annotations

from dataclasses import dataclass

SLOT_ELIGIBILITY = {
    "QB": {"QB"}, "RB": {"RB"}, "WR": {"WR"}, "TE": {"TE"}, "K": {"K"}, "DEF": {"DEF"},
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}
NON_STARTING = {"BN", "IR", "TAXI"}
NESTED_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF", "FLEX", "SUPER_FLEX"]


@dataclass(frozen=True)
class Candidate:
    player_id: str
    positions: frozenset
    points: float


def starting_slots(roster_positions: list) -> list:
    return [s for s in roster_positions if s not in NON_STARTING]


def unsupported_slots(roster_positions: list) -> list:
    return sorted({s for s in roster_positions
                   if s not in SLOT_ELIGIBILITY and s not in NON_STARTING})


def optimal(candidates: list[Candidate], slots: list) -> tuple[float, dict]:
    """Return (total points, {player_id: slot}) for the best legal lineup."""
    nested = all(s in NESTED_ORDER for s in slots)
    single = all(len(c.positions) == 1 for c in candidates)
    if nested and single:
        return _greedy(candidates, slots)
    return _exact(candidates, slots)


def _greedy(candidates, slots):
    pool = sorted(candidates, key=lambda c: (-c.points, c.player_id))
    used, lineup, total = set(), {}, 0.0
    for slot in sorted(slots, key=NESTED_ORDER.index):
        elig = SLOT_ELIGIBILITY[slot]
        for c in pool:
            if c.player_id not in used and c.positions & elig:
                if c.points > 0:
                    used.add(c.player_id)
                    lineup[c.player_id] = slot
                    total += c.points
                break
    return total, lineup


def _exact(candidates, slots):
    n = len(slots)
    if n == 0:
        return 0.0, {}
    big = 1e9
    # Columns: real players, then one empty "nobody" option per slot.
    cols = list(candidates) + [None] * n
    cost = []
    for slot in slots:
        elig = SLOT_ELIGIBILITY[slot]
        row = []
        for c in cols:
            if c is None:
                row.append(0.0)
            elif c.positions & elig:
                row.append(-max(c.points, 0.0))
            else:
                row.append(big)
        cost.append(row)
    assign = hungarian(cost)
    lineup, total = {}, 0.0
    for i, j in enumerate(assign):
        c = cols[j]
        if c is not None and cost[i][j] < 0:
            lineup[c.player_id] = slots[i]
            total += c.points
    return total, lineup


def hungarian(cost: list[list[float]]) -> list[int]:
    """Min-cost assignment for an n×m matrix with n <= m. Returns the column for each row."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result

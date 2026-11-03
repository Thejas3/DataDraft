"""Per-player, per-week projected points from Sleeper's weekly projections (§1), scored
under the league's own settings, plus the D19 schema guard.

Milestone 1 has only the Sleeper source. A week with no Sleeper row for a player (bye,
or no projection published) is 0. The only availability rule applied is the hard one
for Sleeper cells (§5): a player ruled Out, on IR, PUP or suspended scores 0 in the
current week. The baseline and the k-week injury rules arrive with nflverse in
Milestone 2."""

from __future__ import annotations

from dataclasses import dataclass

from .scoring import score

HARD_OUT = {"Out", "IR", "PUP", "Sus", "NA", "DNR"}
REQUIRED_KEYS = ("pass_yd", "rush_yd", "rec_yd", "rec")
GUARD_MIN_SHARE = 0.9


class GuardError(Exception):
    """Sleeper's projections look broken; rulings are paused rather than wrong."""


@dataclass(frozen=True)
class Cell:
    points: float
    source: str  # "sleeper" | "none"
    availability: str = ""  # rule applied, if any


def positions(players: dict, player_id: str) -> frozenset:
    p = players.get(player_id) or {}
    pos = p.get("fantasy_positions") or ([p["position"]] if p.get("position") else [])
    return frozenset(pos)


def project(snap) -> dict[int, dict[str, Cell]]:
    """{week: {player_id: Cell}} for every horizon week in the snapshot."""
    out = {}
    for week, rows in sorted(snap.projections.items()):
        cells = {}
        for row in rows:
            pid = str(row.get("player_id"))
            pts = round(score(row.get("stats") or {}, snap.scoring), 2)
            rule = ""
            status = (snap.players.get(pid) or {}).get("injury_status")
            if week == snap.current_week and status in HARD_OUT:
                pts, rule = 0.0, f"{status}: 0 this week"
            cells[pid] = Cell(pts, "sleeper", rule)
        out[week] = cells
    return out


def cell(matrix: dict, week: int, player_id: str) -> Cell:
    return matrix.get(week, {}).get(player_id) or Cell(0.0, "none")


def guard(snap, matrix: dict, week: int) -> None:
    """D19: the guard set is the league's actual starters from the latest matchups who
    are still rostered, not on bye in `week`, and not ruled out. At least 90% of them
    must project above zero, and the core stat keys must be present at all."""
    rows = snap.projections.get(week) or []
    seen = set()
    for row in rows:
        seen.update((row.get("stats") or {}).keys())
    missing = [k for k in REQUIRED_KEYS if k not in seen]
    if missing:
        raise GuardError(f"Sleeper week {week} projections are missing {', '.join(missing)}")
    rostered = {p for r in snap.rosters for p in (r.get("players") or [])}
    playing = {t for g in snap.schedule if int(g.get("week", 0)) == week
               for t in (g.get("home"), g.get("away"))}
    starters = {p for m in snap.matchups for p in (m.get("starters") or []) if p and p != "0"}
    pool = []
    for pid in starters & rostered:
        info = snap.players.get(pid) or {}
        team = pid if "DEF" in positions(snap.players, pid) else info.get("team")
        if playing and team not in playing:
            continue
        if info.get("injury_status") in HARD_OUT:
            continue
        pool.append(pid)
    if not pool:
        return  # week 1, or no matchups yet: nothing to check against
    projected = sum(1 for pid in pool if cell(matrix, week, pid).points > 0)
    share = projected / len(pool)
    if share < GUARD_MIN_SHARE:
        raise GuardError(
            f"only {projected} of {len(pool)} recent starters have a week {week} projection"
        )

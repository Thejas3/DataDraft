"""Open Question 1: how good are Sleeper's projections and the nflverse baseline, and
do far-week Sleeper projections actually update?

For each past week, every rostered player who played is projected two ways, the way a
ruling made before that week would have: Sleeper's projection for the week, and the
baseline built only from earlier games. Both are scored under the league's settings and
compared with Sleeper's actual stat line. Availability rules are left out on purpose:
only players who played are compared, so this measures projection skill alone."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

from .projections import Baseline, positions
from .scoring import score


@dataclass
class Errors:
    diffs: list = field(default_factory=list)  # projected - actual

    def add(self, projected: float, actual: float) -> None:
        self.diffs.append(projected - actual)

    @property
    def n(self) -> int:
        return len(self.diffs)

    @property
    def mae(self) -> float:
        return sum(abs(d) for d in self.diffs) / self.n if self.n else 0.0

    @property
    def bias(self) -> float:
        return sum(self.diffs) / self.n if self.n else 0.0


@dataclass
class Report:
    weeks: list
    by_source: dict  # (source, position) -> Errors; position "ALL" for the total
    both: dict  # source -> Errors over players both sources projected (fair comparison)
    staleness: dict  # horizon week -> (median days since last_modified, rows)


def _played(stats: dict) -> bool:
    return bool((stats or {}).get("gp") or (stats or {}).get("gms_active"))


def compare(snap, client, weeks: list[int], now: float | None = None) -> Report:
    now = time.time() if now is None else now
    rostered = {p for r in snap.rosters for p in (r.get("players") or [])}
    by_source: dict = {}
    both: dict = {"sleeper": Errors(), "baseline": Errors()}
    for week in weeks:
        actual = {str(r["player_id"]): r.get("stats") or {} for r in
                  client.stats(snap.season, week).data or []}
        proj = {str(r["player_id"]): r.get("stats") or {} for r in
                client.projections(snap.season, week).data or []}
        base = Baseline(snap, week)
        for pid in rostered:
            if not _played(actual.get(pid)):
                continue
            truth = score(actual[pid], snap.scoring)
            pos = next(iter(sorted(positions(snap.players, pid))), "?")
            got = {}
            if pid in proj:
                got["sleeper"] = score(proj[pid], snap.scoring)
            b = base.points(pid)
            if b is not None:
                got["baseline"] = b[0]
            for source, value in got.items():
                for key in ((source, pos), (source, "ALL")):
                    by_source.setdefault(key, Errors()).add(value, truth)
            if len(got) == 2:
                for source, value in got.items():
                    both[source].add(value, truth)
    staleness = {}
    for week, rows in sorted(snap.projections.items()):
        ages = [(now - r["last_modified"] / 1000) / 86400 for r in rows
                if r.get("last_modified") and r["player_id"] in rostered]
        if ages:
            staleness[week] = (statistics.median(ages), len(ages))
    return Report(weeks, by_source, both, staleness)


def render(rep: Report) -> str:
    out = [f"# Projection backtest, weeks {rep.weeks[0]}-{rep.weeks[-1]}\n",
           "Rostered players who played, scored under this league's settings. "
           "Error = projected - actual, in points per game.\n",
           "| Source | Position | Players-weeks | Mean abs error | Bias |", "|---|---|---:|---:|---:|"]
    for (source, pos), e in sorted(rep.by_source.items(), key=lambda kv: (kv[0][0], kv[0][1] != "ALL", kv[0][1])):
        out.append(f"| {source} | {pos} | {e.n} | {e.mae:.2f} | {e.bias:+.2f} |")
    if rep.both["sleeper"].n:
        s, b = rep.both["sleeper"], rep.both["baseline"]
        out.append(f"\nSame {s.n} player-weeks, both sources: Sleeper {s.mae:.2f} vs "
                   f"baseline {b.mae:.2f} mean abs error.")
    if rep.staleness:
        out += ["\n## Do far-week Sleeper projections update?\n",
                "| Week | Median days since Sleeper last updated | Rows |", "|---|---:|---:|"]
        out += [f"| {w} | {d:.1f} | {n} |" for w, (d, n) in rep.staleness.items()]
    return "\n".join(out) + "\n"

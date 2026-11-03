"""Per-player, per-week projected points (§1), scored under the league's own settings,
plus availability across future weeks (§5) and the D19 schema guard.

Source precedence per cell:
1. Sleeper's weekly projection, if Sleeper published a row for that player and week.
2. Otherwise the nflverse baseline: per-game expected stats from ffopportunity (trailing
   4 games blended 50/50 with season to date) for skill players, and the trailing
   4-game average of league-scored points for K and DEF.

The baseline needs the build's nflverse tables, so it exists only in Postgres mode. In
file mode (Milestone 1) a cell with no Sleeper row is 0, as before."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

from .scoring import score

HARD_OUT = {"Out", "IR", "PUP", "Sus", "NA", "DNR"}
REQUIRED_KEYS = ("pass_yd", "rush_yd", "rec_yd", "rec")
GUARD_MIN_SHARE = 0.9

QUESTIONABLE, DOUBTFUL = 0.85, 0.25  # §5 priors; calibrated under Open Question 2
IR_MIN_GAMES = 4  # NFL minimum stay on IR or PUP
MIN_CASES = 20  # §5: designation-specific k needs at least this many cases
TRAIL_GAMES = 4

# ffopportunity expected-stat columns -> Sleeper scoring keys (§1 baseline).
EXPECTED = {"pass_yd": "pass_yards_gained_exp", "pass_td": "pass_touchdown_exp",
            "pass_int": "pass_interception_exp", "rush_yd": "rush_yards_gained_exp",
            "rush_td": "rush_touchdown_exp", "rec": "receptions_exp",
            "rec_yd": "rec_yards_gained_exp", "rec_td": "rec_touchdown_exp"}
# Trailing actuals from player_stats (fumbles lost and 2-pt conversions, §1).
ACTUAL = {"fum_lost": ("sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"),
          "pass_2pt": ("passing_2pt_conversions",), "rush_2pt": ("rushing_2pt_conversions",),
          "rec_2pt": ("receiving_2pt_conversions",)}
SUPPORTED = set(EXPECTED) | set(ACTUAL) | {"bonus_rec_te", "bonus_rec_rb", "bonus_rec_wr"}
DEF_KEYS = {"fum_rec", "fum_rec_td"}
SKILL_PREFIXES = ("pass_", "rush_", "rec", "bonus_", "fum", "pr", "kr", "st_td", "two_pt")


class GuardError(Exception):
    """Sleeper's projections look broken; rulings use the baseline or pause."""


@dataclass(frozen=True)
class Cell:
    points: float
    source: str  # "sleeper" | "baseline" | "trailing" (K/DEF) | "none"
    availability: str = ""  # rule applied, if any
    approx: bool = False  # baseline cell under scoring keys the baseline can't produce


def positions(players: dict, player_id: str) -> frozenset:
    p = players.get(player_id) or {}
    pos = p.get("fantasy_positions") or ([p["position"]] if p.get("position") else [])
    return frozenset(pos)


def team_weeks(snap, team: str | None) -> list[int]:
    """Weeks this Sleeper team plays, from the Sleeper schedule (byes excluded)."""
    if not team:
        return []
    cache = _WEEKS.get(id(snap.schedule))
    if cache is None or cache[0] is not snap.schedule:
        by_team: dict = {}
        for g in snap.schedule:
            for t in (g.get("home"), g.get("away")):
                by_team.setdefault(t, set()).add(int(g["week"]))
        cache = (snap.schedule, {t: sorted(w) for t, w in by_team.items()})
        _WEEKS.clear()
        _WEEKS[id(snap.schedule)] = cache
    return cache[1].get(team, [])


_WEEKS: dict = {}


def _team(snap, pid: str) -> str | None:
    return pid if "DEF" in positions(snap.players, pid) else \
        (snap.players.get(pid) or {}).get("team")


# --- §5 availability -----------------------------------------------------------------

def body_category(text: str | None) -> str:
    """'Left Knee, Ankle' -> 'knee', 'Knee - PCL' -> 'knee'. The first listed part,
    without side or detail."""
    if not text:
        return "unknown"
    first = re.split(r"[,/;(]| - ", str(text))[0].lower()
    first = re.sub(r"\b(left|right|lt|rt)\b", "", first).strip()
    return first or "unknown"


@dataclass
class Absence:
    weeks: tuple  # weeks this player scores 0 (team game weeks only)
    k: int | None = None
    cases: int = 0
    note: str = ""  # the estimated-return line for the player profile

    @property
    def zero(self) -> frozenset:
        return frozenset(self.weeks)


class Availability:
    """One function for the math and the profile note (§5), so they can't disagree."""

    def __init__(self, snap):
        self.snap = snap
        self.k_table = {}
        frame = (snap.nflverse or {}).get("injury_k")
        if frame is not None:
            for d, cat, n, k in frame.select("designation", "category", "n", "k").iter_rows():
                self.k_table[(d, cat)] = (int(n), int(k))
        self.rw = (snap.nflverse or {}).get("rosters_weekly")
        self.history_since = int(frame["since"][0]) if frame is not None and frame.height else None
        self._absence: dict = {}

    def k_for(self, designation: str, category: str) -> tuple[int, int]:
        """(k, cases). Designation-specific with >= 20 cases, else the body-part median
        across designations, else the designation's overall median."""
        exact = self.k_table.get((designation, category))
        if exact and exact[0] >= MIN_CASES:
            return exact[1], exact[0]
        for key in (("ALL", category), (designation, "*")):
            row = self.k_table.get(key)
            if row:
                return row[1], row[0]
        return 1, 0

    def _placement_week(self, pid: str) -> tuple[int, str]:
        """§5: first week the archived Sleeper dumps read IR; before the archive, the first
        week of the current RES stretch in nflverse weekly rosters; else this week."""
        info = self.snap.players.get(pid) or {}
        since = info.get("status_since")
        if since:
            weeks = [int(g["week"]) for g in self.snap.schedule if str(g.get("date", "")) >= since]
            return (min(weeks) if weeks else self.snap.current_week), ""
        gsis = (self.snap.xwalk.get(pid) or (None, None))
        if self.rw is not None and gsis[1] == "gsis":
            rows = sorted(self.rw.filter(self.rw["gsis_id"] == gsis[0])
                          .select("week", "status").iter_rows(), reverse=True)
            start = None
            for week, status in rows:
                if status != "RES":
                    break
                start = int(week)
            if start is not None:
                return start, ""
        return self.snap.current_week, "placement week unknown, treated as this week"

    def absence(self, pid: str) -> Absence:
        if pid not in self._absence:
            self._absence[pid] = self._compute(pid)
        return self._absence[pid]

    def _compute(self, pid: str) -> Absence:
        snap = self.snap
        info = snap.players.get(pid) or {}
        status = info.get("injury_status")
        cur = snap.current_week
        games = [w for w in team_weeks(snap, _team(snap, pid)) if w >= cur]
        if status not in HARD_OUT:
            return Absence(())
        if status not in ("Out", "IR", "PUP"):  # Sus, NA, DNR: this week only
            return Absence(tuple(w for w in games[:1] if w == cur))
        designation = "OUT" if status == "Out" else "IR"
        cat = body_category(info.get("injury_body_part"))
        k, cases = self.k_for(designation, cat) if self.k_table else (1, 0)
        extra = ""
        if designation == "OUT":
            n = k - (0 if cur in games else 1)  # a bye this week counts as the Out week
        else:
            placed, extra = self._placement_week(pid)
            missed = len([w for w in team_weeks(snap, _team(snap, pid)) if placed <= w < cur])
            n = max(IR_MIN_GAMES - missed, k)
        zero = tuple(games[:n])
        ret = next((w for w in games if w not in zero), None)
        note = ""
        if cases:
            since = f" since {self.history_since}" if self.history_since else ""
            note = (f"typical return: week {ret}, based on {cases} similar injuries{since}, "
                    "estimate" if ret else f"likely out for the season, based on {cases} "
                    f"similar injuries{since}, estimate")
        if extra:
            note = f"{note} ({extra})" if note else extra
        return Absence(zero, k if self.k_table else None, cases, note)

    def rule(self, pid: str, week: int, source: str, last_modified=None) -> tuple[float, str]:
        """(multiplier, label) for one cell (§5 'which cells get §5, by source')."""
        info = self.snap.players.get(pid) or {}
        status = info.get("injury_status")
        a = self.absence(pid)
        if week in a.zero:
            if week == self.snap.current_week:
                return 0.0, f"{status}: 0 this week"
            return 0.0, f"{status}: typical absence of {a.k} games" if a.k else f"{status}"
        if week != self.snap.current_week or status not in ("Questionable", "Doubtful"):
            return 1.0, ""
        mult = QUESTIONABLE if status == "Questionable" else DOUBTFUL
        if source != "sleeper":
            return mult, f"{status}: x{mult}"
        since = info.get("status_since")  # 'YYYY-MM-DD' from the status archive
        if since and last_modified and since > _day(last_modified):
            return mult, f"{status}: x{mult} (late designation)"
        return 1.0, ""


def _day(ms) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(int(ms) / 1000, dt.UTC).date().isoformat()


# --- §1 baseline -----------------------------------------------------------------------

@dataclass
class Baseline:
    """Baseline points per player-week for one snapshot. `before_week` limits the
    nflverse games used (the backtest sets it; live rulings use the current week)."""

    snap: object
    before_week: int
    _skill: dict = field(default_factory=dict)
    _kdef: dict = field(default_factory=dict)

    def __post_init__(self):
        nfl = self.snap.nflverse
        sc = self.snap.scoring
        self.approx = any(v for k, v in sc.items() if k not in SUPPORTED and k not in DEF_KEYS
                          and k.startswith(SKILL_PREFIXES))
        opp = nfl["ff_opportunity"]
        opp = opp.filter((opp["week"] < self.before_week) & (opp["season"].cast(str)
                                                             == self.snap.season))
        ps = nfl["player_stats"]
        ps = ps.filter((ps["week"] < self.before_week) & (ps["season_type"] == "REG"))
        self._opp = {}
        for row in opp.sort("week").iter_rows(named=True):
            self._opp.setdefault(row["player_id"], []).append(row)
        self._ps = {}
        for row in ps.sort("week").iter_rows(named=True):
            self._ps.setdefault(row["player_id"], []).append(row)
        self._team_games = _team_games(nfl, self.snap.season, self.before_week)

    @staticmethod
    def _blend(games: list, value) -> float:
        if not games:
            return 0.0
        vals = [value(g) for g in games]
        trail = vals[-TRAIL_GAMES:]
        return 0.5 * sum(trail) / len(trail) + 0.5 * sum(vals) / len(vals)

    def skill_line(self, gsis: str, pos: frozenset) -> dict | None:
        if gsis in self._skill:
            return self._skill[gsis]
        games = self._opp.get(gsis) or []
        line = None
        if games:
            line = {k: self._blend(games, lambda g, c=c: float(g.get(c) or 0))
                    for k, c in EXPECTED.items()}
            actual = self._ps.get(gsis) or []
            for k, cols in ACTUAL.items():
                line[k] = self._blend(actual, lambda g, cs=cols: float(sum(g.get(c) or 0
                                                                            for c in cs)))
            for p in ("TE", "RB", "WR"):
                if p in pos:
                    line[f"bonus_rec_{p.lower()}"] = line["rec"]
                    break
        self._skill[gsis] = line
        return line

    def kdef_points(self, pid: str, key: str, match: str, pos: frozenset) -> float | None:
        """Trailing 4-game average of league-scored points (no opponent adjustment)."""
        cache_key = (pid, key)
        if cache_key in self._kdef:
            return self._kdef[cache_key]
        sc = self.snap.scoring
        pts = None
        if "DEF" in pos:
            lines = [def_line(g) for g in self._team_games.get(key, [])]
        elif match == "gsis":
            lines = [kicker_line(g) for g in self._ps.get(key) or []]
        else:
            lines = [kicker_line(g["own"]) for g in self._team_games.get(key, [])]
        lines = [x for x in lines if x is not None][-TRAIL_GAMES:]
        if lines:
            pts = sum(score(x, sc) for x in lines) / len(lines)
        self._kdef[cache_key] = pts
        return pts

    def points(self, pid: str) -> tuple[float, str, bool] | None:
        """(points per game, source, approx) or None when nflverse has nothing."""
        key, match = self.snap.xwalk.get(pid) or (None, None)
        if not key:
            return None
        pos = positions(self.snap.players, pid)
        if pos & {"K", "DEF"}:
            pts = self.kdef_points(pid, key, match, pos)
            return None if pts is None else (round(pts, 2), "trailing", False)
        if match != "gsis":
            return None
        line = self.skill_line(key, pos)
        if line is None:
            return None
        return round(score(line, self.snap.scoring), 2), "baseline", self.approx


def _team_games(nfl: dict, season: str, before_week: int) -> dict:
    """{team: [{own: team_stats row, opp: opponent row, allowed: points}]} by week."""
    ts = nfl["team_stats"]
    ts = ts.filter((ts["week"] < before_week) & (ts["season_type"] == "REG"))
    by_game = {}
    for row in ts.iter_rows(named=True):
        by_game.setdefault(row["game_id"], {})[row["team"]] = row
    scores = {}
    sched = nfl["schedules"]
    if "home_score" in sched.columns:
        for gid, home, away, hs, as_ in sched.select("game_id", "home_team", "away_team",
                                                     "home_score", "away_score").iter_rows():
            if hs is not None and as_ is not None:
                scores[gid] = {home: as_, away: hs}  # points each team allowed
    out = {}
    for gid, teams in by_game.items():
        if len(teams) != 2:
            continue
        a, b = teams
        for own, opp in ((a, b), (b, a)):
            out.setdefault(own, []).append({"week": teams[own]["week"], "own": teams[own],
                                            "opp": teams[opp],
                                            "allowed": scores.get(gid, {}).get(own)})
    for games in out.values():
        games.sort(key=lambda g: g["week"])
    return out


def kicker_line(r: dict) -> dict:
    g = lambda c: float(r.get(c) or 0)  # noqa: E731
    fgm_50p = g("fg_made_50_59") + g("fg_made_60_")
    return {"fgm": g("fg_made"), "fga": g("fg_att"), "fgmiss": g("fg_missed"),
            "fgm_0_19": g("fg_made_0_19"), "fgm_20_29": g("fg_made_20_29"),
            "fgm_30_39": g("fg_made_30_39"), "fgm_40_49": g("fg_made_40_49"),
            "fgm_50_59": g("fg_made_50_59"), "fgm_60p": g("fg_made_60_"), "fgm_50p": fgm_50p,
            "fgmiss_0_19": g("fg_missed_0_19"), "fgmiss_20_29": g("fg_missed_20_29"),
            "fgmiss_30_39": g("fg_missed_30_39"), "fgmiss_40_49": g("fg_missed_40_49"),
            "fgmiss_50p": g("fg_missed_50_59") + g("fg_missed_60_"),
            "fgm_yds": g("fg_made_distance"), "xpm": g("pat_made"), "xpmiss": g("pat_missed"),
            "xpa": g("pat_att")}


PTS_TIERS = ((0, 0, "pts_allow_0"), (1, 6, "pts_allow_1_6"), (7, 13, "pts_allow_7_13"),
             (14, 20, "pts_allow_14_20"), (21, 27, "pts_allow_21_27"),
             (28, 34, "pts_allow_28_34"), (35, 10**6, "pts_allow_35p"))
YDS_TIERS = ((0, 99, "yds_allow_0_100"), (100, 199, "yds_allow_100_199"),
             (200, 299, "yds_allow_200_299"), (300, 349, "yds_allow_300_349"),
             (350, 399, "yds_allow_350_399"), (400, 449, "yds_allow_400_449"),
             (450, 499, "yds_allow_450_499"), (500, 549, "yds_allow_500_549"),
             (550, 10**6, "yds_allow_550p"))


def _tier(value: float, tiers) -> str:
    return next(name for lo, hi, name in tiers if value <= hi or hi == 10**6)


def def_line(game: dict) -> dict | None:
    """One past game as a Sleeper-style DEF stat line, tiers included, so the league's
    full settings score it (§1)."""
    own, opp, allowed = game["own"], game["opp"], game["allowed"]
    if allowed is None:
        return None
    g = lambda r, c: float(r.get(c) or 0)  # noqa: E731
    yds = g(opp, "passing_yards") - g(opp, "sack_yards_lost") + g(opp, "rushing_yards")
    return {"sack": g(own, "def_sacks"), "int": g(own, "def_interceptions"),
            "fum_rec": g(own, "fumble_recovery_opp"), "def_td": g(own, "def_tds"),
            "safe": g(own, "def_safeties"), "ff": g(own, "def_fumbles_forced"),
            "blk_kick": g(own, "def_fg_blocks") + g(own, "def_punt_blocks"),
            "def_st_td": g(own, "special_teams_tds"), "pts_allow": float(allowed),
            "yds_allow": yds, _tier(allowed, PTS_TIERS): 1.0, _tier(yds, YDS_TIERS): 1.0}


# --- the matrix --------------------------------------------------------------------------

def project(snap, *, use_sleeper: bool = True) -> dict[int, dict[str, Cell]]:
    """{week: {player_id: Cell}} for every horizon week in the snapshot.
    use_sleeper=False is the guard-failure path: the baseline covers every cell."""
    has_nfl = bool(snap.nflverse)
    avail = Availability(snap)
    base = Baseline(snap, snap.current_week) if has_nfl else None
    out = {}
    for week, rows in sorted(snap.projections.items()):
        sleeper = {str(r.get("player_id")): r for r in rows} if use_sleeper else {}
        pids = set(sleeper) | (set(snap.players) if has_nfl else set())
        cells = {}
        for pid in pids:
            row = sleeper.get(pid)
            if row is not None:
                pts = round(score(row.get("stats") or {}, snap.scoring), 2)
                mult, rule = avail.rule(pid, week, "sleeper", row.get("last_modified"))
                cells[pid] = Cell(round(pts * mult, 2), "sleeper", rule)
                continue
            got = base.points(pid) if base else None
            if got is None:
                continue
            pts, source, approx = got
            if week not in team_weeks(snap, _team(snap, pid)):
                cells[pid] = Cell(0.0, source, "bye", approx)
                continue
            mult, rule = avail.rule(pid, week, source)
            cells[pid] = Cell(round(pts * mult, 2), source, rule, approx)
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
    sleeper = {str(r.get("player_id")) for r in rows}
    projected = sum(1 for pid in pool if pid in sleeper and cell(matrix, week, pid).points > 0
                    and cell(matrix, week, pid).source == "sleeper")
    share = projected / len(pool)
    if share < GUARD_MIN_SHARE:
        raise GuardError(
            f"only {projected} of {len(pool)} recent starters have a week {week} projection"
        )


# --- §5 history: k = median games missed per body-part category -------------------------

def injury_k(injuries, rosters_weekly, since: int):
    """From nflverse injury reports and weekly rosters (regular season, fantasy positions):
    OUT cases start the first week a player is reported Out; IR cases start the week the
    weekly roster first reads RES. Games missed = consecutive team games (byes have no
    roster row) the player is Out, RES or INA. Returns a frame of
    (designation, category, n, k, since), plus ALL-designation and '*' fallback rows."""
    import polars as pl

    fantasy = ["QB", "RB", "WR", "TE", "K"]
    inj = injuries.filter((pl.col("game_type") == "REG") & pl.col("position").is_in(fantasy))
    rw = rosters_weekly.filter((pl.col("game_type") == "REG") & pl.col("position").is_in(fantasy)
                               & pl.col("gsis_id").is_not_null())
    reports = {}
    for season, week, gsis, status, body in inj.select(
            "season", "week", "gsis_id", "report_status", "report_primary_injury").iter_rows():
        reports[(season, gsis, int(week))] = (status, body)
    seasons = {}
    for season, week, gsis, status in rw.select("season", "week", "gsis_id", "status").iter_rows():
        seasons.setdefault((season, gsis), {})[int(week)] = status
    cases = []  # (designation, category, games)
    for (season, gsis), weeks in seasons.items():
        order = sorted(weeks)

        def missed(w):
            return weeks[w] in ("RES", "INA") or \
                (reports.get((season, gsis, w), (None,))[0] == "Out")

        def body_near(w):
            for d in range(0, 3):
                r = reports.get((season, gsis, w - d))
                if r and r[1]:
                    return r[1]
            return None

        i = 0
        while i < len(order):
            w = order[i]
            prev_missed = i > 0 and missed(order[i - 1])
            rep = reports.get((season, gsis, w), (None, None))
            start = None
            if weeks[w] == "RES" and (i == 0 or weeks[order[i - 1]] != "RES") and i > 0:
                start = ("IR", body_near(w))
            elif rep[0] == "Out" and not prev_missed:
                start = ("OUT", rep[1])
            if start is None:
                i += 1
                continue
            j = i
            while j < len(order) and missed(order[j]):
                j += 1
            games = j - i
            if games:
                cases.append((start[0], body_category(start[1]), games))
            i = max(j, i + 1)
    rows = []

    def add(designation, category, values):
        if values:
            rows.append((designation, category, len(values),
                         max(1, round(statistics.median(values))), since))

    by = {}
    for d, cat, g in cases:
        by.setdefault((d, cat), []).append(g)
        by.setdefault(("ALL", cat), []).append(g)
        by.setdefault((d, "*"), []).append(g)
    for (d, cat), values in sorted(by.items()):
        add(d, cat, values)
    return pl.DataFrame(rows, schema=["designation", "category", "n", "k", "since"], orient="row")

import json

from conftest import from_recorded, replace, synthetic
from datadraft.cli import render
from datadraft.engine import evaluate
from datadraft.ingest import data_dir

A = ["QB1", "RB1", "RB2", "WR1", "WR2", "TE1", "WR3"]
B = ["QB2", "RB3", "RB4", "WR4", "WR5", "TE2", "RB5"]
PTS = {"QB1": 20, "RB1": 15, "RB2": 10, "WR1": 14, "WR2": 12, "TE1": 8, "WR3": 9,
       "QB2": 19, "RB3": 16, "RB4": 6, "WR4": 13, "WR5": 11, "TE2": 9, "RB5": 7}
RECORDED_TRADE = "Marvin Harrison Jr., Dalton Kincaid for MarShawn Lloyd"


def run(snap, text, **kw):
    kw.setdefault("use_court", False)
    return evaluate({"type": "trade", "text": text}, snap.snapshot_id, snapshot=snap, **kw)


def test_dynasty_is_unsupported(recorded_raw):
    r = run(from_recorded(recorded_raw), RECORDED_TRADE).ruling
    assert r.verdict == "UNSUPPORTED" and "dynasty" in r.reason


def test_picks_and_idp_are_unsupported():
    snap = synthetic({1: A, 2: B}, PTS)
    assert run(snap, "WR3 Player, 2027 1st for RB3 Player").ruling.verdict == "UNSUPPORTED"
    idp = synthetic({1: A, 2: B}, PTS, slots=["QB", "RB", "DL", "BN"])
    assert "DL" in run(idp, "WR3 Player for RB3 Player").ruling.reason


def test_past_deadline_and_empty_horizon_are_invalid():
    late = synthetic({1: A, 2: B}, PTS, settings={"trade_deadline": 8})
    assert "deadline" in run(late, "WR3 Player for RB3 Player").ruling.reason
    over = replace(synthetic({1: A, 2: B}, PTS, settings={"trade_deadline": 0}), current_week=11)
    assert run(over, "WR3 Player for RB3 Player").ruling.reason == "season over / no unlocked weeks"


def test_guard_pauses_rulings_when_projections_vanish(recorded):
    blank = {w: [dict(r, stats={k: 0 for k in r["stats"]}) for r in rows]
             for w, rows in recorded.projections.items()}
    res = run(replace(recorded, projections=blank), RECORDED_TRADE)
    assert res.error.startswith("Projections look wrong today")
    assert render(res).startswith("# Trade Court: paused")


def test_recorded_league_regression(recorded):
    """Real Sleeper data (week 8, 2026): numbers are pinned so engine changes are visible."""
    res = run(recorded, RECORDED_TRADE)
    d = res.ruling.delta
    assert d.weeks == tuple(range(8, 18))
    assert (res.ruling.verdict, d.me.delta, d.them.delta) == ("REJECT", -1.54, 0.86)
    assert run(recorded, RECORDED_TRADE).ruling.delta.me.per_week == d.me.per_week  # deterministic


def test_ledger_freezes_once_with_per_week_numbers():
    snap = synthetic({1: A, 2: B}, PTS)
    key = run(snap, "RB2 Player for RB3 Player").ledger_key
    assert run(snap, "RB2 Player for RB3 Player").ledger_key == key
    rows = [json.loads(l) for l in (data_dir() / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    me = rows[0]["trade"]["me"]
    assert rows[0]["verdict"] == "ACCEPT" and set(me) >= {"before", "after", "per_week"}


def test_render_joins_team_names_only_at_render_time():
    out = render(run(synthetic({1: A, 2: B}, PTS), "RB2 Player for RB3 Player"))
    assert "# Trade Court: ACCEPT" in out and "from Team 2" in out

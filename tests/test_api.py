"""The HTTP API: passphrase gate, league allowlist, rate limit, spend cap, progressive
court load, public ruling page, and the waiver / start-sit / player routes."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from datadraft import db
from datadraft.api import Settings, caveats, create_app
from datadraft.pipeline import run_daily
from test_court import GOOD, FakeClient
from test_pipeline import DAY, TEST_URL, Clock, FakeSleeper, fake_history, fake_nflverse

PASS = "touchdown-tuesday"
TRADE_NAMES = ("Marvin Harrison Jr.", "Dalton Kincaid", "MarShawn Lloyd")


@pytest.fixture
def world(monkeypatch, recorded_raw):
    try:
        setup = db.connect(TEST_URL)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no test Postgres at {TEST_URL}: {e}")
    schema = f"t_{uuid.uuid4().hex[:10]}"
    setup.execute(f"create schema {schema}")
    url = f"{TEST_URL}?options=-csearch_path%3D{schema}"
    monkeypatch.setenv("DATABASE_URL", url)  # every API thread connects into the schema
    c = db.connect(url)
    db.init(c)
    clock = Clock()
    run_daily(c, FakeSleeper(db.PgPayloadStore(c), recorded_raw, clock), ["fixture"],
              nflverse=fake_nflverse, history=fake_history, now=clock)
    yield {"raw": recorded_raw, "clock": clock, "conn": c}
    c.close()
    setup.execute(f"drop schema {schema} cascade")
    setup.close()


def app_client(world, **kw):
    def factory():
        return FakeSleeper(db.PgPayloadStore(db.conn()), world["raw"], world["clock"])

    court = kw.pop("court_client", None)
    settings = Settings(passphrase=PASS, secret="s3cret", leagues=["fixture"], **kw)
    app = create_app(settings, client_factory=factory, court_client=court, now=world["clock"])
    return TestClient(app)


def logged_in(world, **kw):
    t = app_client(world, **kw)
    assert t.post("/api/session", json={"passphrase": PASS}).status_code == 204
    return t


def pid(raw, name):
    return next(p for p, v in raw["players"].items() if v.get("full_name") == name)


def trade_body(raw):
    a, b, c = (pid(raw, n) for n in TRADE_NAMES)
    return {"give": [a, b], "get": [c]}


def test_passphrase_gate(world):
    t = app_client(world)
    assert t.get("/api/session").status_code == 401
    bad = t.post("/api/session", json={"passphrase": "nope"})
    assert bad.status_code == 401 and bad.json()["detail"] == "That's not it."
    assert t.post("/api/session", json={"passphrase": PASS}).status_code == 204
    assert t.get("/api/session").json()["leagues"] == ["fixture"]
    t.cookies.clear()
    t.cookies.set("dd_session", "9999999999.forged")
    assert t.get("/api/session").status_code == 401


def test_repeated_wrong_passphrases_are_throttled(world):
    t = app_client(world)
    for _ in range(10):
        t.post("/api/session", json={"passphrase": "nope"})
    assert t.post("/api/session", json={"passphrase": PASS}).status_code == 429


def test_leagues_off_the_allowlist_are_hidden(world):
    t = logged_in(world)
    assert t.get("/api/leagues/123456").status_code == 404
    summary = t.get("/api/leagues/fixture").json()
    assert summary["week"] == 8 and len(summary["teams"]) == len(world["raw"]["rosters"])


def test_ruling_then_progressive_court_then_public_page(world):
    fake = FakeClient([GOOD])
    t = logged_in(world, court_client=fake)
    r = t.post("/api/leagues/fixture/rulings", json=trade_body(world["raw"])).json()
    assert (r["verdict"], r["trade"]["me"]["delta"], r["trade"]["them"]["delta"]) == \
        ("REJECT", -1.54, 0.86)  # the pinned regression numbers
    assert len(r["slug"]) >= 22 and r["court_pending"] and fake.sent == []
    court = t.post(f"/api/rulings/{r['slug']}/court").json()
    assert court["for"][0]["evidence"][0]["id"] == "E2"
    assert "{E" not in court["for"][0]["text"]  # placeholders rendered
    assert t.post(f"/api/rulings/{r['slug']}/court").json() == court  # stored, not re-run
    assert len(fake.sent) == 1
    anon = app_client(world)
    page = anon.get(f"/api/public/rulings/{r['slug']}")
    assert page.status_code == 200 and page.headers["x-robots-tag"].startswith("noindex")
    body = page.json()
    assert body["verdict"] == "REJECT" and body["court"]["for"]
    assert "snapshot_id" not in body and "league_id" not in body
    assert anon.get("/api/public/rulings/nope").status_code == 404
    assert anon.get(f"/api/rulings/{r['slug']}").status_code == 401
    recent = t.get("/api/leagues/fixture/rulings").json()
    assert recent[0]["slug"] == r["slug"]


def test_rate_limit_per_league(world):
    t = logged_in(world, rulings_per_hour=2)
    for _ in range(2):
        assert t.post("/api/leagues/fixture/rulings", json=trade_body(world["raw"])).status_code == 200
    assert t.post("/api/leagues/fixture/rulings", json=trade_body(world["raw"])).status_code == 429


def test_spend_cap_keeps_numbers_and_withholds_arguments(world):
    fake = FakeClient([GOOD])
    t = logged_in(world, court_client=fake, spend_cap=0.01)
    r = t.post("/api/leagues/fixture/rulings", json=trade_body(world["raw"])).json()
    court = t.post(f"/api/rulings/{r['slug']}/court").json()
    assert fake.sent == [] and "spend cap" in court["notice"] and court["for"] == []
    assert r["trade"]["me"]["delta"] == -1.54


def test_spend_is_recorded_and_counts_against_the_day(world):
    t = logged_in(world, court_client=FakeClient([GOOD, GOOD]), spend_cap=0.09)
    for _ in range(2):
        r = t.post("/api/leagues/fixture/rulings", json=trade_body(world["raw"])).json()
        last = t.post(f"/api/rulings/{r['slug']}/court").json()
    # A call's worst case is ~$0.084 ($0.08 of output + input), so the first fits under
    # $0.09 and spends $0.018; the second's worst case no longer fits in what's left.
    assert "spend cap" in last["notice"]
    spent = world["conn"].execute("select sum(cost_usd) from api_events where kind = 'llm'")
    assert round(spent.fetchone()[0], 3) == 0.018


def test_invalid_trade_returns_a_reason_panel(world):
    t = logged_in(world)
    raw = world["raw"]
    mine = raw["rosters"][0]["players"]
    r = t.post("/api/leagues/fixture/rulings", json={"give": [mine[0]], "get": [mine[1]]}).json()
    assert r["verdict"] == "INVALID" and "same roster" in r["reason"] and not r["court_pending"]


def test_sleeper_down_with_nothing_cached_is_a_503_with_retry(world):
    t = logged_in(world)
    world["conn"].execute("delete from payload_index")  # nothing to fall back on
    from datadraft.ingest import FetchError

    original = FakeSleeper._http

    def down(self, url):
        raise FetchError("down")

    FakeSleeper._http = down
    try:
        res = t.get("/api/leagues/fixture")
    finally:
        FakeSleeper._http = original
    assert res.status_code == 503 and res.json() == {"error": "Can't reach Sleeper right now.",
                                                     "retry": True}


def test_waivers_startsit_and_player_routes(world):
    t = logged_in(world)
    w = t.get("/api/leagues/fixture/waivers", params={"roster_id": 1}).json()
    assert {"picks", "considered", "weeks", "checked_at"} <= set(w)
    s = t.get("/api/leagues/fixture/startsit", params={"roster_id": 1}).json()
    assert s["week"] == 8 and len(s["slots"]) == 9  # the fixture's starting slots
    assert t.get("/api/leagues/fixture/waivers", params={"roster_id": 99}).status_code == 404
    p = pid(world["raw"], "MarShawn Lloyd")
    prof = t.get(f"/api/leagues/fixture/players/{p}").json()
    assert prof["name"] == "MarShawn Lloyd" and prof["projections"] and prof["roster_id"]
    assert t.get("/api/leagues/fixture/players/nobody").status_code == 404


def test_caveats_follow_the_fixed_severity_order():
    from types import SimpleNamespace

    notes = ["Depth-as-insurance not modeled (v1): uneven trades lean toward consolidation.",
             "Data is stale: projections are from 2026-10-27T08:00Z, over 30 h ago.",
             "Rosters as of 2026-10-29T08:00Z: Sleeper didn't respond."]
    res = SimpleNamespace(ruling=SimpleNamespace(notes=notes, delta=None),
                          snapshot=None, matrix={})
    assert [c["kind"] for c in caveats(res)] == ["stale_rosters", "stale_build", "depth"]

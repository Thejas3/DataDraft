"""DataDraft HTTP API (Milestone 2, step 8). Postgres mode only.

Access (§ Access control): leagues on DATADRAFT_LEAGUES only, behind one shared
passphrase (POST /api/session sets a signed, HttpOnly cookie). The one public route is
GET /api/public/rulings/{slug}: a single ruling by its unlisted 128-bit slug, noindex.

Limits: DATADRAFT_RULINGS_PER_HOUR rulings per league per hour (default 30), and a
daily LLM spend cap, DATADRAFT_SPEND_CAP dollars (default 2). Past the cap, rulings
still return their numbers; the court's arguments say they're unavailable today.

Progressive load (D30): POST .../rulings returns the verdict and numbers at once; the
client then calls POST /api/rulings/{slug}/court for the cited arguments. That second
call re-runs evaluate() on the same pinned snapshot, so the numbers are identical.

D7: this module imports only the engine's public surface (enforced by import-linter).
Sleeper text (team and player names) is returned as data; pages must escape it (D8)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import db
from .engine import copy_dm, evaluate, player_name, player_profile, positions
from .ingest import FetchError, SleeperClient
from .snapshot import NoBuild, build_snapshot, load_snapshot

COOKIE = "dd_session"
ATTRIBUTION = "Data: nflverse (CC BY 4.0), Sleeper"
LOGIN_FAILS, LOGIN_WINDOW_S = 10, 15 * 60
STALE_H = 30


@dataclass
class Settings:
    passphrase: str
    secret: str
    leagues: list = field(default_factory=list)
    spend_cap: float = 2.0
    rulings_per_hour: int = 30
    cookie_secure: bool = False
    session_days: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        missing = [k for k in ("DATADRAFT_PASSPHRASE", "DATADRAFT_SECRET", "DATABASE_URL")
                   if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Set {', '.join(missing)} before starting the API.")
        return cls(passphrase=os.environ["DATADRAFT_PASSPHRASE"],
                   secret=os.environ["DATADRAFT_SECRET"],
                   leagues=[x for x in os.environ.get("DATADRAFT_LEAGUES", "").split(",") if x],
                   spend_cap=float(os.environ.get("DATADRAFT_SPEND_CAP", "2")),
                   rulings_per_hour=int(os.environ.get("DATADRAFT_RULINGS_PER_HOUR", "30")),
                   cookie_secure=os.environ.get("DATADRAFT_COOKIE_SECURE") == "1")


class Login(BaseModel):
    passphrase: str


class TradeIn(BaseModel):
    give: list[str]
    get: list[str]


# --- serialization ---------------------------------------------------------------------

def team_name(snap, roster_id: int) -> str:
    owner = next((r.get("owner_id") for r in snap.rosters if int(r["roster_id"]) == roster_id),
                 None)
    user = next((u for u in snap.users if u.get("user_id") == owner), {})
    return (user.get("metadata") or {}).get("team_name") or user.get("display_name") \
        or f"Roster {roster_id}"


def player(snap, pid: str) -> dict:
    info = snap.players.get(pid) or {}
    return {"id": pid, "name": player_name(snap.players, pid),
            "positions": sorted(positions(snap.players, pid)), "team": info.get("team"),
            "injury_status": info.get("injury_status")}


def _side(snap, s) -> dict:
    return {"roster_id": s.roster_id, "team": team_name(snap, s.roster_id), "delta": s.delta,
            "per_week": {str(w): v for w, v in s.per_week.items()},
            "forced_drops": [player(snap, p) for p in s.forced_drops]}


def _trade(snap, d) -> dict:
    return {"give": [player(snap, p) for p in d.trade.give],
            "get": [player(snap, p) for p in d.trade.get], "weeks": list(d.weeks),
            "me": _side(snap, d.me), "them": _side(snap, d.them),
            "they_likely": "yes" if d.them.delta > 0 else "no"}


# D28: one line under the verdict shows the most severe caveat, in this fixed order.
CAVEAT_ORDER = (("rosters as of", "stale_rosters"), ("data is stale", "stale_build"),
                ("approx. scoring", "approx_scoring"), ("depth-as-insurance", "depth"),
                ("late designation", "late_designation"))


def caveats(result) -> list[dict]:
    r, snap, matrix = result.ruling, result.snapshot, result.matrix
    notes = list(r.notes)
    if r.delta:
        pids = r.delta.trade.give + r.delta.trade.get
        cells = [matrix.get(w, {}).get(p) for w in r.delta.weeks for p in pids]
        if any(c is not None and c.approx for c in cells):
            notes.append("Approx. scoring: some weeks use the nflverse baseline, which can't "
                         "produce every stat your league scores.")
        if any(c is not None and "late designation" in c.availability for c in cells):
            notes.append("Late designation: an injury designation arrived after Sleeper's "
                         "last projection update, so it was applied on top.")
    out = []
    for text in dict.fromkeys(notes):
        low = text.lower()
        rank = next((i for i, (k, _) in enumerate(CAVEAT_ORDER) if k in low), len(CAVEAT_ORDER))
        kind = CAVEAT_ORDER[rank][1] if rank < len(CAVEAT_ORDER) else "other"
        out.append({"kind": kind, "rank": rank, "text": text})
    return sorted(out, key=lambda c: c["rank"])


def ruling_body(result) -> dict:
    snap, r = result.snapshot, result.ruling
    dm = None
    if r.verdict == "ACCEPT" and r.delta:
        dm = copy_dm(snap, r.delta)  # D31: proposes the trade as-is
    elif r.verdict == "COUNTER" and r.counter:
        dm = copy_dm(snap, r.counter)  # D31: proposes the counter
    cav = caveats(result)
    return {"verdict": r.verdict, "reason": r.reason, "band": r.band,
            "trade": _trade(snap, r.delta) if r.delta else None,
            "counter": _trade(snap, r.counter) if r.counter else None,
            "copy_dm": dm, "caveat": cav[0]["text"] if cav else None, "caveats": cav,
            "paused": result.error or None, "snapshot_id": snap.snapshot_id,
            "as_of": {"build": snap.build_as_of, "rosters": snap.league_as_of},
            "week": snap.current_week, "attribution": ATTRIBUTION}


def court_body(result) -> dict:
    c = result.court
    if c is None:
        return {"for": [], "against": [], "rationale": [], "notice": None}
    by_id = {e["id"]: e for e in result.evidence}
    sections = {k: [{"text": a.text, "evidence": [by_id[e] for e in a.evidence_ids
                                                  if e in by_id]}
                    for a in c.arguments.get(k) or []]
                for k in ("for", "against", "rationale")}
    return {**sections, "notice": c.notice or None}


PUBLIC_KEYS = ("verdict", "reason", "trade", "counter", "as_of", "week", "attribution")


# --- the app ---------------------------------------------------------------------------

def create_app(settings: Settings, *, client_factory=None, court_client=None,
               now=time.time) -> FastAPI:
    app = FastAPI(title="DataDraft", docs_url=None, redoc_url=None)

    def client() -> SleeperClient:
        if client_factory:
            return client_factory()
        return SleeperClient(db.PgPayloadStore(db.conn()), league_max_age=600)

    # -- auth --
    def sign(expiry: int) -> str:
        mac = hmac.new(settings.secret.encode(), f"v1:{expiry}".encode(), hashlib.sha256)
        return f"{expiry}.{mac.hexdigest()}"

    def authed(request: Request) -> None:
        token = request.cookies.get(COOKIE, "")
        expiry, _, _ = token.partition(".")
        if not (expiry.isdigit() and int(expiry) > now()
                and hmac.compare_digest(token, sign(int(expiry)))):
            raise HTTPException(401, "Enter the league passphrase.")

    def league(league_id: str, _: None = Depends(authed)) -> str:
        if league_id not in settings.leagues:
            raise HTTPException(404, "No such league here.")
        return league_id

    @app.exception_handler(FetchError)
    def _sleeper_down(request, exc):
        return JSONResponse({"error": "Can't reach Sleeper right now.", "retry": True},
                            status_code=503)

    @app.exception_handler(NoBuild)
    def _no_build(request, exc):
        return JSONResponse({"error": f"No projections yet: {exc}.", "retry": False},
                            status_code=503)

    def events(kind: str, key: str, since: float) -> tuple[int, float]:
        n, cost = db.conn().execute(
            "select count(*), coalesce(sum(cost_usd), 0) from api_events where kind = %s "
            "and key = %s and at >= to_timestamp(%s)", (kind, key, since)).fetchone()
        return int(n), float(cost)

    def record(kind: str, key: str, cost: float = 0.0) -> None:
        db.conn().execute("insert into api_events (kind, key, at, cost_usd) values "
                          "(%s, %s, to_timestamp(%s), %s)", (kind, key, now(), cost))

    @app.post("/api/session", status_code=204)
    def login(body: Login, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        fails, _ = events("login_fail", ip, now() - LOGIN_WINDOW_S)
        if fails >= LOGIN_FAILS:
            raise HTTPException(429, "Too many tries. Wait a few minutes.")
        if not hmac.compare_digest(body.passphrase.encode(), settings.passphrase.encode()):
            record("login_fail", ip)
            raise HTTPException(401, "That's not it.")
        expiry = int(now()) + settings.session_days * 86400
        response.set_cookie(COOKIE, sign(expiry), max_age=settings.session_days * 86400,
                            httponly=True, samesite="lax", secure=settings.cookie_secure)

    @app.get("/api/session")
    def session(_: None = Depends(authed)):
        return {"ok": True, "leagues": settings.leagues}

    @app.get("/api/status")
    def status(_: None = Depends(authed)):
        row = db.conn().execute(
            "select b.build_id, b.as_of from current_build c join builds b using (build_id)"
        ).fetchone()
        if row is None:
            return {"build_id": None, "as_of": None, "stale": True}
        age_h = (now() - row[1]) / 3600
        return {"build_id": row[0], "age_h": round(age_h, 1), "stale": age_h > STALE_H,
                "as_of": dt.datetime.fromtimestamp(row[1], dt.UTC).strftime("%Y-%m-%dT%H:%MZ")}

    # -- league --
    @app.get("/api/leagues/{league_id}")
    def league_summary(league_id: str = Depends(league)):
        snap = build_snapshot(client(), league_id)
        if not snap.league:
            raise HTTPException(404, "Sleeper doesn't know this league.")
        teams = []
        for r in sorted(snap.rosters, key=lambda r: int(r["roster_id"])):
            rid = int(r["roster_id"])
            held = set(r.get("reserve") or []) | set(r.get("taxi") or [])
            teams.append({"roster_id": rid, "name": team_name(snap, rid),
                          "players": [dict(player(snap, p), reserve=p in held)
                                      for p in r.get("players") or []]})
        n = db.conn().execute("select count(*) from rulings where league_id = %s",
                              (league_id,)).fetchone()[0]
        return {"league_id": league_id, "name": snap.league.get("name"), "season": snap.season,
                "week": snap.current_week, "teams": teams, "rulings_saved": n,
                "as_of": {"build": snap.build_as_of, "rosters": snap.league_as_of},
                "warnings": list(snap.warnings)}

    # -- trade court --
    @app.post("/api/leagues/{league_id}/rulings")
    def new_ruling(body: TradeIn, league_id: str = Depends(league)):
        made, _ = events("ruling", league_id, now() - 3600)
        if made >= settings.rulings_per_hour:
            raise HTTPException(429, f"{settings.rulings_per_hour} rulings an hour is the "
                                     "limit for this league. Try again shortly.")
        snap = build_snapshot(client(), league_id)
        action = {"type": "trade", "give": body.give, "get": body.get}
        result = evaluate(action, snap.snapshot_id, snapshot=snap, use_court=False)
        record("ruling", league_id)
        out = ruling_body(result)
        slug = secrets.token_urlsafe(16)  # 128 bits
        db.conn().execute(
            "insert into rulings (slug, league_id, snapshot_id, ledger_key, action, body) "
            "values (%s, %s, %s, %s, %s, %s)",
            (slug, league_id, snap.snapshot_id, result.ledger_key or None, _json(action),
             _json(out)))
        return {"slug": slug, **out, "court_pending": result.ruling.delta is not None}

    def _ruling_row(slug: str):
        row = db.conn().execute("select league_id, snapshot_id, action, body, court, "
                                "created_at from rulings where slug = %s", (slug,)).fetchone()
        if row is None:
            raise HTTPException(404, "This ruling doesn't exist or was removed.")
        return row

    @app.post("/api/rulings/{slug}/court")
    def ruling_court(slug: str, _: None = Depends(authed)):
        league_id, snapshot_id, action, body, court, _ = _ruling_row(slug)
        if court is not None:
            return court
        if not body.get("trade"):  # INVALID / UNSUPPORTED: nothing to argue
            return {"for": [], "against": [], "rationale": [], "notice": None}
        day = dt.datetime.fromtimestamp(now(), dt.UTC).replace(hour=0, minute=0, second=0,
                                                              microsecond=0).timestamp()
        _, spent = events("llm", "all", day)
        snap = load_snapshot(snapshot_id)  # pinned: same numbers as the first call
        result = evaluate(action, snapshot_id, snapshot=snap, court_client=court_client,
                          court_budget_usd=max(0.0, settings.spend_cap - spent))
        if result.court and result.court.cost_usd:
            record("llm", "all", result.court.cost_usd)
        out = court_body(result)
        db.conn().execute("update rulings set court = %s where slug = %s", (_json(out), slug))
        return out

    @app.get("/api/rulings/{slug}")
    def get_ruling(slug: str, _: None = Depends(authed)):
        league_id, _, _, body, court, created = _ruling_row(slug)
        return {"slug": slug, "league_id": league_id, **body, "court": court,
                "created_at": created.isoformat()}

    @app.get("/api/leagues/{league_id}/rulings")
    def recent_rulings(limit: int = 3, league_id: str = Depends(league)):
        rows = db.conn().execute(
            "select slug, body, created_at from rulings where league_id = %s "
            "order by created_at desc limit %s", (league_id, max(1, min(limit, 50)))).fetchall()
        return [{"slug": s, "verdict": b["verdict"], "trade": b.get("trade"),
                 "created_at": c.isoformat()} for s, b, c in rows]

    @app.get("/api/public/rulings/{slug}")
    def public_ruling(slug: str, response: Response):
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        _, _, _, body, court, created = _ruling_row(slug)
        return {**{k: body.get(k) for k in PUBLIC_KEYS}, "court": court,
                "created_at": created.isoformat()}

    # -- waivers, start/sit, players --
    def roster_or_404(snap, roster_id: int) -> None:
        if not any(int(r["roster_id"]) == roster_id for r in snap.rosters):
            raise HTTPException(404, f"No roster {roster_id} in this league.")

    @app.get("/api/leagues/{league_id}/waivers")
    def get_waivers(roster_id: int, league_id: str = Depends(league)):
        snap = build_snapshot(client(), league_id)
        roster_or_404(snap, roster_id)
        res = evaluate({"type": "waiver", "roster_id": roster_id}, snap.snapshot_id,
                       snapshot=snap)
        if res.error:
            return {"error": res.error, "picks": []}
        w = res.waivers
        return {"roster_id": roster_id, "weeks": list(w.weeks), "considered": w.considered,
                "picks": [{"add": player(snap, p.add),
                           "drop": player(snap, p.drop) if p.drop else None,
                           "status": p.status, "delta": p.delta,
                           "per_week": {str(k): v for k, v in p.side.per_week.items()},
                           "nflverse_match": bool((snap.xwalk.get(p.add) or (None,))[0])
                           if snap.xwalk else None}
                          for p in w.picks],
                "checked_at": snap.league_as_of, "notes": res.notes,
                "as_of": {"build": snap.build_as_of, "rosters": snap.league_as_of}}

    @app.get("/api/leagues/{league_id}/startsit")
    def get_startsit(roster_id: int, league_id: str = Depends(league)):
        c = client()
        snap = build_snapshot(c, league_id)
        roster_or_404(snap, roster_id)
        live = c.matchups(league_id, snap.current_week, max_age=60)
        action = {"type": "startsit", "roster_id": roster_id, "now": now(),
                  "live": next((m for m in live.data or [] if int(m["roster_id"]) == roster_id),
                               {}),
                  "live_as_of": dt.datetime.fromtimestamp(live.fetched_at, dt.UTC)
                  .strftime("%Y-%m-%dT%H:%MZ")}
        res = evaluate(action, snap.snapshot_id, snapshot=snap)
        if res.error:
            return {"error": res.error, "slots": []}
        s = res.startsit
        cells = res.matrix.get(s.week, {})
        return {"roster_id": roster_id, "week": s.week, "gain": s.gain, "total": s.total,
                "start": [player(snap, p) for p in s.start],
                "sit": [player(snap, p) for p in s.sit],
                "slots": [{"slot": p.slot, "player": player(snap, p.player_id)
                           if p.player_id else None, "points": p.points, "locked": p.locked,
                           "source": p.source, "availability": p.availability,
                           "approx": bool(getattr(cells.get(p.player_id), "approx", False))}
                          for p in s.slots],
                "warnings": s.warnings + res.notes,
                "as_of": {"status": snap.build_as_of, "live": s.live_as_of}}

    @app.get("/api/leagues/{league_id}/players/{player_id}")
    def get_player(player_id: str, league_id: str = Depends(league)):
        snap = build_snapshot(client(), league_id)
        prof = player_profile(snap, player_id)
        if prof is None:
            raise HTTPException(404, "Player not found.")
        owner = next((int(r["roster_id"]) for r in snap.rosters
                      if player_id in (r.get("players") or [])), None)
        return {**prof, "roster_id": owner,
                "team_name": team_name(snap, owner) if owner else None,
                "attribution": ATTRIBUTION}

    return app


def _json(x) -> str:
    import json

    return json.dumps(x)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_app(Settings.from_env()), host=host, port=port)

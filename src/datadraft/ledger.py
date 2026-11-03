"""Freeze each ruling with the per-week numbers it was made on (D18), so it can be
graded against actual results later (grading itself is phase 2, D22)."""

from __future__ import annotations

import hashlib
import json
import time

from . import ENGINE_VERSION
from .delta import Side, TradeDelta
from .ingest import data_dir


def _side(s: Side) -> dict:
    return {"roster_id": s.roster_id, "before": s.before, "after": s.after,
            "per_week": s.per_week, "delta": s.delta, "forced_drops": list(s.forced_drops)}


def _trade(d: TradeDelta) -> dict:
    return {"give": list(d.trade.give), "get": list(d.trade.get),
            "weeks": list(d.weeks), "me": _side(d.me), "them": _side(d.them)}


def ruling_key(action: dict, snapshot_id: str) -> str:
    blob = json.dumps([action, snapshot_id, ENGINE_VERSION], sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def freeze(action: dict, snapshot_id: str, league_id: str, ruling) -> str:
    """Append the ruling unless this exact (action, snapshot, engine) is already there."""
    key = ruling_key(action, snapshot_id)
    path = data_dir() / "ledger.jsonl"
    if path.exists() and any(json.loads(l)["key"] == key for l in path.read_text().splitlines()):
        return key
    row = {
        "key": key, "frozen_at": time.time(), "engine_version": ENGINE_VERSION,
        "league_id": league_id, "snapshot_id": snapshot_id, "action": action,
        "verdict": ruling.verdict, "reason": ruling.reason, "band": ruling.band,
        "trade": _trade(ruling.delta) if ruling.delta else None,
        "counter": _trade(ruling.counter) if ruling.counter else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")
    return key

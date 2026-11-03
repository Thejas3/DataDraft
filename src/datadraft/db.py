"""Postgres storage (Milestone 2). Turned on by DATABASE_URL; without it everything
keeps Milestone 1's JSON files under ~/.datadraft, so the CLI still works offline.

What lives here:
- payloads / payload_index: raw league-state payloads keyed by content hash (O6)
- builds + current_build: the daily projection build and the one-row pointer that
  publishes it (D5). A build is immutable once the pointer names it.
- build_players / build_projections / build_projection_rows / build_tables: the build's
  contents, pruned to relevant players (D13), plus nflverse tables as parquet
- status_archive: one row per player per day, the source for IR placement weeks (§5)
- snapshots, ledger: derived snapshots (§2) and frozen rulings (D18)"""

from __future__ import annotations

import hashlib
import json
import os

SCHEMA = """
create table if not exists payloads (
    sha text primary key,
    body jsonb not null
);
create table if not exists payload_index (
    key text not null,
    sha text not null,
    fetched_at double precision not null
);
create index if not exists payload_index_key on payload_index (key, fetched_at desc);

create table if not exists builds (
    build_id text primary key,
    created_at timestamptz not null default now(),
    as_of double precision not null,
    season text not null,
    state_week int not null,
    weeks int[] not null,
    schedule_sha text not null,
    guard jsonb not null,
    counts jsonb not null
);
create table if not exists current_build (
    one boolean primary key default true check (one),
    build_id text not null references builds on delete restrict,
    flipped_at timestamptz not null default now()
);
create table if not exists build_players (
    build_id text not null references builds on delete cascade,
    player_id text not null,
    info jsonb not null,
    nflverse_key text,
    match text,
    primary key (build_id, player_id)
);
create table if not exists build_projection_rows (
    build_id text not null references builds on delete cascade,
    week int not null,
    player_id text not null,
    team text,
    opponent text,
    last_modified bigint,
    primary key (build_id, week, player_id)
);
create table if not exists build_projections (
    build_id text not null references builds on delete cascade,
    week int not null,
    player_id text not null,
    stat text not null,
    value double precision not null
);
-- No 4-column primary key: it doubled the table's size. The pipeline is the only
-- writer, and readers fold rows into {player: {stat: value}}.
create index if not exists build_projections_week on build_projections (build_id, week);
create table if not exists build_tables (
    build_id text not null references builds on delete cascade,
    name text not null,
    nrows int not null,
    parquet bytea not null,
    primary key (build_id, name)
);
create table if not exists status_archive (
    day date not null,
    player_id text not null,
    injury_status text,
    team text,
    primary key (day, player_id)
);
create table if not exists snapshots (
    snapshot_id text primary key,
    build_id text not null,
    created_at timestamptz not null default now(),
    manifest jsonb not null
);
create table if not exists rulings (
    slug text primary key,  -- 128-bit random, unlisted (§ Access control)
    league_id text not null,
    snapshot_id text not null,
    ledger_key text,
    action jsonb not null,
    body jsonb not null,  -- the ruling as the API serves it
    court jsonb,  -- filled by the second, progressive call (D30)
    created_at timestamptz not null default now()
);
create index if not exists rulings_league on rulings (league_id, created_at desc);
create table if not exists api_events (
    kind text not null,  -- 'ruling' (rate limit) | 'llm' (spend cap) | 'login_fail'
    key text not null,  -- league id, or client address for login failures
    at timestamptz not null default now(),
    cost_usd double precision not null default 0
);
create index if not exists api_events_kind on api_events (kind, key, at);
create table if not exists ledger (
    key text primary key,
    frozen_at double precision not null,
    snapshot_id text not null,
    row jsonb not null
);
"""

import threading

_local = threading.local()  # one connection per thread: the API serves from a pool


def url() -> str:
    return os.environ.get("DATABASE_URL", "")


def enabled() -> bool:
    return bool(url())


def connect(dsn: str | None = None):
    import psycopg

    return psycopg.connect(dsn or url(), autocommit=True)


def conn():
    """This thread's connection. Writes that must be atomic use conn.transaction()."""
    c = getattr(_local, "conn", None)
    if c is None or c.closed:
        c = _local.conn = connect()
    return c


def use(connection) -> None:
    """Point this thread at an existing connection (tests, the pipeline)."""
    _local.conn = connection


def init(c=None) -> None:
    (c or conn()).execute(SCHEMA)


class PgPayloadStore:
    """The PayloadStore interface on Postgres. Bulk payloads (the ~5 MB players dump and
    the projection weeks) are indexed by hash but not kept: the build stores their pruned,
    typed form instead (D13), which keeps a 14-day history inside a free-tier database."""

    BULK = ("/v1/players/", "/projections/")

    def __init__(self, c=None):
        self.c = c or conn()

    def put(self, key: str, raw: bytes, fetched_at: float) -> str:
        sha = hashlib.sha256(raw).hexdigest()
        from psycopg.types.json import Jsonb

        with self.c.transaction():
            if not key.startswith(self.BULK):
                self.c.execute("insert into payloads (sha, body) values (%s, %s) "
                               "on conflict do nothing", (sha, Jsonb(json.loads(raw))))
            self.c.execute("insert into payload_index (key, sha, fetched_at) values (%s, %s, %s)",
                           (key, sha, fetched_at))
        return sha

    def get(self, sha: str) -> object:
        row = self.c.execute("select body from payloads where sha = %s", (sha,)).fetchone()
        if row is None:
            raise KeyError(f"payload {sha[:12]} is not stored (pruned, or a bulk payload)")
        return row[0]

    def latest(self, key: str):
        from .ingest import Fetched

        row = self.c.execute(
            "select i.sha, i.fetched_at, p.body from payload_index i join payloads p using (sha) "
            "where i.key = %s order by i.fetched_at desc limit 1", (key,)).fetchone()
        return Fetched(row[2], row[0], row[1]) if row else None

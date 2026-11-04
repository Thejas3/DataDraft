"""A seeded API server for the Playwright end-to-end test (web/e2e). Not a pytest file.

The recorded league (as redraft) is built into a throwaway Postgres schema with fake
nflverse tables, and the court always returns valid cited arguments, so the browser
test runs the real FastAPI + Next.js code with no network and no Claude calls.

    python tests/e2e_server.py 8766"""

import atexit
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_court import GOOD  # noqa: E402
from test_pipeline import TEST_URL, Clock, FakeSleeper, fake_history, fake_nflverse  # noqa: E402

from datadraft import db  # noqa: E402
from datadraft.api import Settings, create_app  # noqa: E402
from datadraft.pipeline import run_daily  # noqa: E402

PASS = "e2e-passphrase"


class AlwaysGood:
    def __init__(self):
        self.messages = self.beta = self

    def create(self, **kw):
        from types import SimpleNamespace

        return SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                               usage=SimpleNamespace(input_tokens=2000, output_tokens=500),
                               content=[SimpleNamespace(type="text", text=json.dumps(GOOD))])


def main(port: int) -> None:
    import uvicorn

    raw = json.loads((Path(__file__).parent / "fixtures/league_2026_w8.json").read_text())
    schema = f"e2e_{uuid.uuid4().hex[:8]}"
    setup = db.connect(TEST_URL)
    setup.execute(f"create schema {schema}")
    atexit.register(lambda: setup.execute(f"drop schema {schema} cascade"))
    url = f"{TEST_URL}?options=-csearch_path%3D{schema}"
    os.environ["DATABASE_URL"] = url
    c = db.connect(url)
    db.init(c)
    clock = Clock()
    run_daily(c, FakeSleeper(db.PgPayloadStore(c), raw, clock), ["fixture"],
              nflverse=fake_nflverse, history=fake_history, now=clock)
    app = create_app(Settings(passphrase=PASS, secret="e2e", leagues=["fixture"]),
                     client_factory=lambda: FakeSleeper(db.PgPayloadStore(db.conn()), raw, clock),
                     court_client=AlwaysGood(), now=clock)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 8766)

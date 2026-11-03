# DataDraft

Trade rulings for Sleeper redraft leagues. It scores every remaining week with your
league's own scoring and lineup slots, then rules ACCEPT, REJECT, TOSS-UP or COUNTER.

```
python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'

datadraft leagues <sleeper_username>          # find your league id
datadraft trade <league_id> "A, B for C"      # you send A and B, you get C
```

Your team is whichever roster holds A and B, so anyone in the league can run it.
Set `ANTHROPIC_API_KEY` to add the court's sourced for/against arguments; without it
the ruling and numbers still print.

## Storage: files or Postgres

Without `DATABASE_URL`, each `trade` fetches Sleeper directly and caches raw payloads
under `~/.datadraft` (Milestone 1).

With `DATABASE_URL`, rulings sit on a **daily build** in Postgres: Sleeper projections
and players plus nflverse stats, injuries, schedules and the Sleeper-to-nflverse ID
crosswalk. Rosters are still fetched live for every ruling.

```
docker compose up -d
export DATABASE_URL=postgresql://datadraft:datadraft@localhost:5433/datadraft
export DATADRAFT_LEAGUES=<league_id>          # leagues the build keeps players for
datadraft db init
datadraft pipeline                            # once a day, ~08:00 UTC
datadraft status                              # current build, age, guard result
datadraft trade <league_id> "A, B for C"
```

A build is published only after it passes validation, and the previous build stays
current if a day fails. The last 14 builds are kept. Projections older than 30 h show a
stale notice. `.github/workflows/daily.yml` runs the pipeline on a schedule; it needs
the `DATABASE_URL` and `DATADRAFT_LEAGUES` repo secrets.

Not supported yet: keeper/dynasty leagues, draft picks or FAAB in trades, IDP slots.

Run the tests with `.venv/bin/pytest`. The Postgres tests need the compose database
(or `DATADRAFT_TEST_DATABASE_URL`) and skip without it.

Data: nflverse (CC BY 4.0), Sleeper.

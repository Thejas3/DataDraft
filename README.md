# DataDraft

Trade rulings for Sleeper redraft leagues. It scores every remaining week with your
league's own scoring and lineup slots, then rules ACCEPT, REJECT, TOSS-UP or COUNTER.

```
python3.13 -m venv .venv && .venv/bin/pip install -e '.[dev]'

datadraft leagues <sleeper_username>          # find your league id
datadraft trade <league_id> "A, B for C"      # you send A and B, you get C
datadraft waivers <league_id> --team <you>    # best adds, and who to drop for them
datadraft startsit <league_id> --team <you>   # this week's best lineup
```

`--team` takes your Sleeper username, team name or roster number. Waivers checks the top
50 free agents against your bench and labels each one free agent or waivers ("best add
if you win the claim"); FAAB bids aren't modeled. Start/sit leaves players whose games
have kicked off in their slots with their actual points and only fills the open slots.

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
datadraft compare <league_id> --weeks 6-8     # backtest Sleeper vs the baseline
```

In this mode, a player-week Sleeper didn't project uses an nflverse baseline instead:
expected stats from the last 4 games blended with season to date, or a trailing
average for K and DEF. If Sleeper's projections fail the daily sanity check, the
baseline covers every cell and the ruling says so. Injured players are zeroed for
the typical absence for their body part, learned from injury reports since 2015, and
IR players for at least the rest of the 4-game minimum.

A build is published only after it passes validation, and the previous build stays
current if a day fails. The last 14 builds are kept. Projections older than 30 h show a
stale notice. `.github/workflows/daily.yml` runs the pipeline on a schedule; it needs
the `DATABASE_URL` and `DATADRAFT_LEAGUES` repo secrets.

## HTTP API

```
export DATADRAFT_PASSPHRASE=<shared with your league>  DATADRAFT_SECRET=<random string>
datadraft serve --port 8000
```

Only leagues in `DATADRAFT_LEAGUES` are served, behind the shared passphrase
(`POST /api/session`). A trade ruling returns its numbers right away
(`POST /api/leagues/{id}/rulings`), and the cited arguments come from a second call
(`POST /api/rulings/{slug}/court`). Each ruling gets an unlisted link; its public,
read-only view is `GET /api/public/rulings/{slug}`. Also: `/api/leagues/{id}`,
`.../waivers?roster_id=`, `.../startsit?roster_id=`, `.../players/{player_id}`,
`/api/status`.

Limits: `DATADRAFT_RULINGS_PER_HOUR` per league (default 30) and a daily Claude spend
cap, `DATADRAFT_SPEND_CAP` dollars (default 2). Past the cap, rulings keep their numbers
and say the arguments are unavailable today. Court calls use Claude's server-side
refusal fallback. Set `DATADRAFT_COOKIE_SECURE=1` behind HTTPS.

Not supported yet: keeper/dynasty leagues, draft picks or FAAB in trades, IDP slots.

Run the tests with `.venv/bin/pytest`. The Postgres tests need the compose database
(or `DATADRAFT_TEST_DATABASE_URL`) and skip without it.

Data: nflverse (CC BY 4.0), Sleeper.

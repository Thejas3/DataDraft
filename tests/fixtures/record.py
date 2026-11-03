"""Record a trimmed, anonymized Sleeper fixture from a saved snapshot (D11: tests never
call Sleeper). Usage: DATADRAFT_HOME=... python tests/fixtures/record.py <snapshot_id> <name>

Players and projections are trimmed to rostered players; leaguemates' names and avatars
are replaced with "Team N"."""

import json
import sys
from pathlib import Path

from datadraft.snapshot import load_snapshot

KEEP_PLAYER = ("first_name", "last_name", "full_name", "position", "fantasy_positions",
               "team", "injury_status")


def main(snapshot_id: str, name: str) -> None:
    s = load_snapshot(snapshot_id)
    rostered = {p for r in s.rosters for p in (r.get("players") or [])}
    owners = {r.get("owner_id"): r["roster_id"] for r in s.rosters}
    users = [{"user_id": f"u{owners[u['user_id']]}", "display_name": f"Team {owners[u['user_id']]}",
              "metadata": {}} for u in s.users if u["user_id"] in owners]
    league = {k: s.league[k] for k in ("league_id", "season", "settings", "scoring_settings",
                                       "roster_positions", "total_rosters")}
    league["name"] = "Fixture League"
    league["league_id"] = "fixture"
    rosters = [{k: r.get(k) for k in ("roster_id", "players", "starters", "reserve", "taxi")}
               | {"owner_id": f"u{r['roster_id']}"} for r in s.rosters]
    players = {p: {k: v for k, v in s.players[p].items() if k in KEEP_PLAYER}
               for p in sorted(rostered) if p in s.players}
    projections = {w: [{"player_id": r["player_id"], "week": r.get("week"),
                        "stats": {k: v for k, v in r["stats"].items() if v}}
                       for r in rows if r["player_id"] in rostered]
                   for w, rows in s.projections.items()}
    matchups = [{"roster_id": m["roster_id"], "starters": m["starters"]} for m in s.matchups]
    out = {"season": s.season, "current_week": s.current_week, "today": s.today.isoformat(),
           "build_as_of": s.build_as_of, "league_as_of": s.league_as_of, "league": league,
           "rosters": rosters, "users": users, "players": players,
           "projections": projections, "schedule": s.schedule, "matchups": matchups}
    path = Path(__file__).parent / f"{name}.json"
    path.write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main(*sys.argv[1:3])

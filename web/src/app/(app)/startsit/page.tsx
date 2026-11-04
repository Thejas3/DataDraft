"use client";

import Link from "next/link";
import { NeedTeam, useLeague } from "@/components/league";
import type { Player } from "@/lib/api";
import { names, signed, when } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Slot = { slot: string; player: Player | null; points: number; locked: boolean;
              source: string; availability: string; approx: boolean };
type StartSit = { week: number; gain: number; total: number; start: Player[]; sit: Player[];
                  slots: Slot[]; warnings: string[]; as_of: { status: string; live: string };
                  error?: string };

export default function StartSitPage() {
  return <NeedTeam><Lineup /></NeedTeam>;
}

function Lineup() {
  const { league, rosterId } = useLeague();
  const { data, error, loading, reload } = useApi<StartSit>(`/api/leagues/${league.league_id}/startsit?roster_id=${rosterId}`);
  const startIds = new Set(data?.start.map((p) => p.id));
  return (
    <>
      <h2>Start/Sit · Week {league.week}</h2>
      {loading && <ul className="list">{[0, 1, 2, 3, 4, 5].map((i) => <li key={i}><div className="skel" /></li>)}</ul>}
      {error && <p className="notice n-err row" role="alert">{error.message}{error.retry && <button className="btn btn-secondary" onClick={reload}>Retry</button>}</p>}
      {data?.error && <p className="notice n-warn">{data.error}</p>}
      {data && !data.error && (
        <>
          {data.start.length > 0 ? (
            <p className="notice n-info">Start {names(data.start)}; sit {names(data.sit) || "nobody"}: {signed(data.gain, "pts")} projected.</p>
          ) : data.slots.every((s) => s.locked || !s.player) ? (
            <p className="notice n-info">No games left for your roster this week.</p>
          ) : (
            <p className="slate">Your lineup is already the best one.</p>
          )}
          {data.warnings.map((w, i) => <p key={i} className="notice n-warn">{w}</p>)}
          <ul className="list">
            {data.slots.map((s, i) => (
              <li key={i} className={`slot${s.locked ? " locked" : ""}`}>
                <span className="pos">{s.slot.replace("SUPER_FLEX", "SF")}</span>
                <span>
                  {s.player ? (
                    <>
                      <Link href={`/players/${s.player.id}`}>{s.player.name}</Link>
                      {s.locked && <span className="tag" style={{ marginLeft: 6 }}>Locked</span>}
                      {s.player.injury_status && <span className="tag" style={{ marginLeft: 6 }}>{s.player.injury_status}</span>}
                      <span className="mono slate" style={{ display: "block" }}>
                        {s.locked ? `actual · ${when(data.as_of.live)}` : [s.source, s.availability, s.approx && "approx. scoring"].filter(Boolean).join(" · ")}
                      </span>
                    </>
                  ) : <span className="slate">(empty)</span>}
                </span>
                <span className="pts">{s.points.toFixed(1)}</span>
                {s.player && startIds.has(s.player.id) && <span className="swap">Move {s.player.name} in here</span>}
              </li>
            ))}
          </ul>
          <p className="slate small">Projected total {data.total.toFixed(1)} (locked players at actual points). Statuses as of {when(data.as_of.status)}.</p>
          <p><a className="btn btn-secondary" href={`https://sleeper.com/leagues/${league.league_id}/team`} target="_blank" rel="noreferrer">Open Sleeper</a></p>
        </>
      )}
    </>
  );
}

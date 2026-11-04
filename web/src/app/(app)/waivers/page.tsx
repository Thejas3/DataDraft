"use client";

import Link from "next/link";
import { NeedTeam, useLeague } from "@/components/league";
import { pos, signed, spoken, when } from "@/lib/format";
import { reason, type WaiverPick as Pick } from "@/lib/waivers";
import { useApi } from "@/lib/hooks";

type Waivers = { picks: Pick[]; considered: number; weeks: number[]; checked_at: string;
                 notes: string[]; error?: string };

export default function WaiversPage() {
  return <NeedTeam><WaiverList /></NeedTeam>;
}

function WaiverList() {
  const { league, rosterId } = useLeague();
  const { data, error, loading, reload } = useApi<Waivers>(`/api/leagues/${league.league_id}/waivers?roster_id=${rosterId}`);
  return (
    <>
      <h2>Waivers</h2>
      {loading && <ul className="list">{[0, 1, 2, 3, 4].map((i) => <li key={i}><div className="skel" /></li>)}</ul>}
      {error && <p className="notice n-err row" role="alert">{error.message}{error.retry && <button className="btn btn-secondary" onClick={reload}>Retry</button>}</p>}
      {data?.error && <p className="notice n-warn">{data.error}</p>}
      {data && !data.error && (
        <>
          <p className="slate">Weeks {data.weeks[0]}–{data.weeks[data.weeks.length - 1]} · {data.considered} free agents checked against your bench</p>
          {data.picks.length === 0 ? (
            <p className="notice n-info">No free agent beats your bench right now (checked {when(data.checked_at)}).</p>
          ) : (
            <ul className="list">
              {data.picks.map((p) => (
                <li key={p.add.id} className="wrow">
                  <div>
                    <b>Add <Link href={`/players/${p.add.id}`}>{p.add.name}</Link></b> <span className="slate">{pos(p.add)} · {p.add.team ?? "FA"}</span>
                    {" · "}{p.drop ? <>Drop {p.drop.name}</> : <>open roster spot</>}
                    <div className="row" style={{ gap: 8, marginTop: 6 }}>
                      <span className="tag">{p.status === "waivers" ? "Waivers" : "Free agent"}</span>
                      {p.status === "waivers" && <span className="small slate">best add if you win the claim</span>}
                      {p.nflverse_match === false && <span className="tag">no nflverse match</span>}
                    </div>
                    <div className="small slate" style={{ marginTop: 4 }}>{reason(p)}</div>
                  </div>
                  <div className="gainbig gain">
                    <span aria-hidden="true">{signed(p.delta)}</span>
                    <span className="sr-only">{spoken(p.delta)}</span>
                    <small className="slate small" style={{ display: "block", fontFamily: "var(--body)", fontWeight: 600 }} aria-hidden="true">pts/wk</small>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {data.notes.map((n, i) => <p key={i} className="notice n-warn">{n}</p>)}
        </>
      )}
    </>
  );
}

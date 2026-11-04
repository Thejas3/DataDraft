"use client";

import Link from "next/link";
import { useLeague } from "@/components/league";
import { when } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Profile = {
  player_id: string; name: string; positions: string[]; team: string | null;
  injury_status: string | null; injury_body_part: string | null; status_as_of: string;
  estimated_return: string | null; nflverse_match: boolean; roster_id: number | null;
  team_name: string | null; notes: string[];
  projections: { week: number; points: number; source: string; availability: string; approx: boolean }[];
  usage: Record<string, number>[];
};

const USAGE: [string, string][] = [["targets", "Tgt"], ["receptions", "Rec"], ["receiving_yards", "Rec yd"],
  ["carries", "Car"], ["rushing_yards", "Rush yd"], ["attempts", "Att"], ["passing_yards", "Pass yd"]];

/** D43: who and how healthy, then the rest-of-season projection and usage trend. */
export function Profile({ id }: { id: string }) {
  const { league, rosterId } = useLeague();
  const { data, error } = useApi<Profile>(`/api/leagues/${league.league_id}/players/${id}`);
  if (error) return <p className="notice n-err">{error.status === 404 ? "Player not found." : error.message} <Link href="/players">Search</Link></p>;
  if (!data) return <><div className="skel" style={{ height: 48, width: "50%" }} /><div className="skel" style={{ height: 200 }} /></>;
  const cols = USAGE.filter(([k]) => data.usage.some((u) => (u[k] ?? 0) > 0));
  const last6 = data.usage.slice(-6);
  return (
    <>
      <h1 style={{ fontSize: "clamp(40px, 6vw, 64px)" }}>{data.name}</h1>
      <p className="slate" style={{ marginTop: 8 }}>
        {data.positions.join("/")} · {data.team ?? "FA"}{data.team_name && <> · on {data.team_name}</>}
      </p>
      {data.injury_status ? (
        <p className="notice n-warn">
          <b>{data.injury_status}</b>{data.injury_body_part && <> ({data.injury_body_part})</>}
          {data.estimated_return && <> · {data.estimated_return}</>}
          <span className="mono slate" style={{ display: "block" }}>status as of {when(data.status_as_of)}</span>
        </p>
      ) : <p className="slate small">No current injury designation.</p>}
      {data.roster_id !== null && data.roster_id !== rosterId && (
        <p><Link className="btn btn-primary" href={`/court?get=${data.player_id}`}>Evaluate a trade with him</Link></p>
      )}
      <section style={{ marginTop: 40 }} aria-labelledby="proj-h">
        <h3 id="proj-h">Rest-of-season projection</h3>
        <table className="grid" style={{ marginTop: 12 }}>
          <thead><tr><th>Week</th><th className="num">Pts</th><th>Source</th></tr></thead>
          <tbody>
            {data.projections.map((p) => (
              <tr key={p.week}>
                <td>{p.week}</td><td className="num">{p.points.toFixed(1)}</td>
                <td className="mono">{[p.source, p.availability, p.approx && "approx. scoring"].filter(Boolean).join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section style={{ marginTop: 40 }} aria-labelledby="use-h">
        <h3 id="use-h">Usage, last 6 games</h3>
        {!data.nflverse_match ? <p className="slate">No nflverse match: stats and injury history are hidden; projections are Sleeper only.</p>
          : !last6.length ? <p className="slate">No games this season yet.</p> : (
          <table className="grid" style={{ marginTop: 12 }}>
            <thead><tr><th>Week</th>{cols.map(([, l]) => <th key={l} className="num">{l}</th>)}</tr></thead>
            <tbody>
              {last6.map((u) => (
                <tr key={u.week}><td>{u.week}</td>{cols.map(([k]) => <td key={k} className="num">{u[k] ?? 0}</td>)}</tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

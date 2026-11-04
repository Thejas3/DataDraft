"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { NeedTeam, useLeague } from "@/components/league";
import { api, ApiError, type Player, type Ruling, type Team } from "@/lib/api";
import { names, pos, VERDICTS, when } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Recent = { slug: string; verdict: Ruling["verdict"]; trade: Ruling["trade"]; created_at: string };

export function TradeEntry() {
  return <NeedTeam><Entry /></NeedTeam>;
}

function Entry() {
  const { league, rosterId } = useLeague();
  const router = useRouter();
  const params = useSearchParams();
  const preGet = params.get("get");
  const mine = league.teams.find((t) => t.roster_id === rosterId)!;
  const owner = preGet ? league.teams.find((t) => t.players.some((p) => p.id === preGet)) : undefined;
  const [themId, setThemId] = useState<number | null>(owner && owner.roster_id !== rosterId ? owner.roster_id : null);
  const [give, setGive] = useState<string[]>([]);
  const [get, setGet] = useState<string[]>(owner && owner.roster_id !== rosterId && preGet ? [preGet] : []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const recent = useApi<Recent[]>(`/api/leagues/${league.league_id}/rulings?limit=3`);
  const them = league.teams.find((t) => t.roster_id === themId) ?? null;

  async function evaluate() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<Ruling>(`/api/leagues/${league.league_id}/rulings`, {
        method: "POST", body: JSON.stringify({ give, get }),
      });
      router.push(`/court/r/${r.slug}`);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
      setBusy(false);
    }
  }

  return (
    <>
      <h2 style={{ marginBottom: 24 }}>Trade Court</h2>
      <div className="entry">
        <Side title="You give" team={mine} picked={give} onPick={setGive} />
        <section className="side" aria-labelledby="get-h">
          <h3 id="get-h">You get</h3>
          <label className="field" htmlFor="them">Trade with
            <select id="them" value={themId ?? ""} onChange={(e) => { setThemId(Number(e.target.value)); setGet([]); }}>
              <option value="" disabled>Pick a team</option>
              {league.teams.filter((t) => t.roster_id !== rosterId).map((t) => (
                <option key={t.roster_id} value={t.roster_id}>{t.name}</option>
              ))}
            </select>
          </label>
          {them && <Side team={them} picked={get} onPick={setGet} bare />}
        </section>
      </div>
      <div className="row" style={{ marginTop: 32 }}>
        <button className="btn btn-primary" disabled={busy || !give.length || !get.length} onClick={evaluate}>
          {busy ? "Ruling…" : "Evaluate"}
        </button>
        {(!give.length || !get.length) && <span className="slate">Pick a team and players to trade.</span>}
      </div>
      {error && (
        <p className="notice n-err row" role="alert" style={{ marginTop: 16 }}>
          {error.message}
          {error.retry && <button className="btn btn-secondary" onClick={evaluate}>Retry</button>}
        </p>
      )}
      <section style={{ marginTop: 64 }} aria-labelledby="recent-h">
        <h3 id="recent-h">Receipts: {league.rulings_saved} rulings saved</h3>
        <ul className="list">
          {recent.data?.map((r) => (
            <li key={r.slug}>
              <Link href={`/court/r/${r.slug}`}>
                {VERDICTS[r.verdict].icon} {VERDICTS[r.verdict].word}
                {r.trade && <> · {names(r.trade.give)} for {names(r.trade.get)}</>}
              </Link>{" "}
              <span className="mono slate">{when(r.created_at)}</span>
            </li>
          ))}
          {recent.data?.length === 0 && <li className="slate">No rulings yet.</li>}
        </ul>
      </section>
    </>
  );
}

function Side({ title, team, picked, onPick, bare }: {
  title?: string; team: Team; picked: string[]; onPick: (ids: string[]) => void; bare?: boolean;
}) {
  const [q, setQ] = useState("");
  const id = `filter-${team.roster_id}`;
  const shown = useMemo(() => {
    const k = q.trim().toLowerCase();
    return team.players.filter((p) => !p.reserve && (!k || p.name.toLowerCase().includes(k)))
      .sort((a, b) => a.positions.join().localeCompare(b.positions.join()) || a.name.localeCompare(b.name));
  }, [team, q]);
  const toggle = (p: Player) => onPick(picked.includes(p.id) ? picked.filter((x) => x !== p.id) : [...picked, p.id]);
  const byId = new Map(team.players.map((p) => [p.id, p]));
  const body = (
    <>
      <div className="selected" aria-label={`Selected from ${team.name}`}>
        {picked.map((pid) => (
          <button key={pid} className="pill-x" onClick={() => onPick(picked.filter((x) => x !== pid))}
                  aria-label={`Remove ${byId.get(pid)?.name}`}>
            {byId.get(pid)?.name} ✕
          </button>
        ))}
      </div>
      <label className="field" htmlFor={id} style={{ marginTop: 12 }}>Filter {team.name}
        <input id={id} type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      <ul className="picklist">
        {shown.map((p) => (
          <li key={p.id}>
            <button aria-pressed={picked.includes(p.id)} onClick={() => toggle(p)}>
              <span>{p.name}{p.injury_status && <span className="tag" style={{ marginLeft: 8 }}>{p.injury_status}</span>}</span>
              <span className="slate">{pos(p)} · {p.team ?? "FA"}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
  if (bare) return body;
  return (
    <section className="side" aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`}>{title}</h3>
      <p className="slate small" style={{ margin: 0 }}>{team.name}</p>
      {body}
    </section>
  );
}

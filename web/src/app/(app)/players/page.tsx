"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useLeague } from "@/components/league";
import { pos } from "@/lib/format";

export default function PlayersPage() {
  const { league } = useLeague();
  const [q, setQ] = useState("");
  const all = useMemo(() => league.teams.flatMap((t) => t.players.map((p) => ({ ...p, owner: t.name }))), [league]);
  const k = q.trim().toLowerCase();
  const shown = k ? all.filter((p) => p.name.toLowerCase().includes(k)).slice(0, 50) : [];
  return (
    <>
      <h2>Players</h2>
      <label className="field" htmlFor="psearch" style={{ maxWidth: 420, marginTop: 24 }}>Search rostered players
        <input id="psearch" type="search" value={q} onChange={(e) => setQ(e.target.value)} />
      </label>
      <ul className="list">
        {shown.map((p) => (
          <li key={p.id}><Link href={`/players/${p.id}`}>{p.name}</Link> <span className="slate">{pos(p)} · {p.team ?? "FA"} · {p.owner}</span></li>
        ))}
        {k && !shown.length && <li className="slate">Player not found.</li>}
      </ul>
    </>
  );
}

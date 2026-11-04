"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, type League, type Status } from "@/lib/api";
import { when } from "@/lib/format";
import { useTheme } from "@/lib/hooks";

type Ctx = {
  league: League;
  rosterId: number | null;
  setRosterId: (id: number) => void;
  announce: (msg: string) => void;
  toast: (msg: string) => void;
};

const LeagueContext = createContext<Ctx | null>(null);

export function useLeague(): Ctx {
  const c = useContext(LeagueContext);
  if (!c) throw new Error("useLeague outside <Shell>");
  return c;
}

const TABS = [
  { href: "/court", label: "Trade Court" },
  { href: "/waivers", label: "Waivers" },
  { href: "/startsit", label: "Start-Sit" },
  { href: "/players", label: "Players" },
];

type Loaded = { lg: League; st: Status };

async function fetchLeague(): Promise<Loaded> {
  const s = await api<{ leagues: string[] }>("/api/session");
  if (!s.leagues.length) throw new ApiError(404, "No league is configured on the server.");
  const [lg, st] = await Promise.all([api<League>(`/api/leagues/${s.leagues[0]}`), api<Status>("/api/status")]);
  return { lg, st };
}

export function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const [league, setLeague] = useState<League | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [rosterId, setRoster] = useState<number | null>(null);
  const [live, setLive] = useState("");
  const [toastMsg, setToastMsg] = useState("");
  const [theme, flipTheme] = useTheme();

  const apply = useCallback((p: Promise<Loaded>) => {
    p.then(({ lg, st }) => {
      setError(null);
      setLeague(lg);
      setStatus(st);
      const saved = Number(localStorage.getItem(`dd-roster-${lg.league_id}`));
      setRoster(lg.teams.some((t) => t.roster_id === saved) ? saved : null);
    }).catch((e) => {
      if (e instanceof ApiError && e.status === 401) {
        router.replace(`/login?next=${encodeURIComponent(location.pathname + location.search)}`);
        return;
      }
      setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
    });
  }, [router]);
  const load = useCallback(() => apply(fetchLeague()), [apply]);

  // Once per mount: moving between tabs doesn't need a league refetch.
  useEffect(() => apply(fetchLeague()), [apply]);

  const setRosterId = (id: number) => {
    setRoster(id);
    if (league) localStorage.setItem(`dd-roster-${league.league_id}`, String(id));
  };
  const announce = useCallback((msg: string) => setLive(msg), []);
  const toast = useCallback((msg: string) => {
    setToastMsg(msg);
    setLive(msg);
    window.setTimeout(() => setToastMsg(""), 3000);
  }, []);

  const tabs = (
    <>
      {TABS.map((t) => (
        <Link key={t.href} href={t.href} aria-current={path.startsWith(t.href) ? "page" : undefined}>
          {t.label}
        </Link>
      ))}
    </>
  );

  return (
    <>
      <header className="top">
        <div className="wrap">
          <Link className="wordmark" href="/court">DataDraft</Link>
          {league && <span className="league">{league.name} · Wk {league.week}</span>}
          <nav className="tabs" aria-label="Sections">{tabs}</nav>
          {league && (
            <select id="team-pick" aria-label="Your team" value={rosterId ?? ""} style={{ width: "auto", minHeight: 36 }}
                    onChange={(e) => setRosterId(Number(e.target.value))}>
              <option value="" disabled>Your team…</option>
              {league.teams.map((t) => <option key={t.roster_id} value={t.roster_id}>{t.name}</option>)}
            </select>
          )}
          <button className="toggle" onClick={flipTheme} aria-pressed={theme === "dark"}>
            {theme === "dark" ? "Day" : "Night"}
          </button>
        </div>
      </header>
      {status?.stale && (
        <div className="banner" role="status">
          <div className="wrap">Projections last updated {when(status.as_of)}.</div>
        </div>
      )}
      <main id="main">
        <div className="wrap">
          {error && (
            <div className="notice n-err row" role="alert">
              <span>{error.message}</span>
              {error.retry && <button className="btn btn-secondary" onClick={load}>Retry</button>}
            </div>
          )}
          {!league && !error && <><div className="skel" style={{ width: "40%" }} /><div className="skel" /></>}
          {league && (
            <LeagueContext.Provider value={{ league, rosterId, setRosterId, announce, toast }}>
              {children}
            </LeagueContext.Provider>
          )}
        </div>
      </main>
      <footer className="site"><div className="wrap">Data: nflverse (CC BY 4.0), Sleeper</div></footer>
      <nav className="tabbar" aria-label="Sections">{tabs}</nav>
      <div className="sr-only" aria-live="polite" role="status">{live}</div>
      {toastMsg && <div className="toast" aria-hidden="true">{toastMsg}</div>}
    </>
  );
}

/** A section that needs "your team" first. */
export function NeedTeam({ children }: { children: React.ReactNode }) {
  const { league, rosterId, setRosterId } = useLeague();
  if (rosterId !== null) return <>{children}</>;
  return (
    <div style={{ maxWidth: 420 }}>
      <label className="field" htmlFor="need-team">Which team is yours?
        <select id="need-team" defaultValue="" onChange={(e) => setRosterId(Number(e.target.value))}>
          <option value="" disabled>Pick your team</option>
          {league.teams.map((t) => <option key={t.roster_id} value={t.roster_id}>{t.name}</option>)}
        </select>
      </label>
    </div>
  );
}

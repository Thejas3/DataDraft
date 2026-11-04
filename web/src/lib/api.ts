// Types mirror src/datadraft/api.py. Sleeper text (team and player names) arrives raw;
// React escapes it when rendering (D8), and nothing here uses dangerouslySetInnerHTML.

export type Player = {
  id: string;
  name: string;
  positions: string[];
  team: string | null;
  injury_status: string | null;
  reserve?: boolean;
};

export type Side = {
  roster_id: number;
  team: string;
  delta: number;
  per_week: Record<string, number>;
  forced_drops: Player[];
};

export type TradeOut = {
  give: Player[];
  get: Player[];
  weeks: number[];
  me: Side;
  them: Side;
  they_likely: "yes" | "no";
};

export type Verdict = "ACCEPT" | "REJECT" | "TOSS-UP" | "COUNTER" | "INVALID" | "UNSUPPORTED";

export type Caveat = { kind: string; rank: number; text: string };

export type Ruling = {
  slug: string;
  verdict: Verdict;
  reason: string;
  band: number;
  trade: TradeOut | null;
  counter: TradeOut | null;
  copy_dm: string | null;
  caveat: string | null;
  caveats: Caveat[];
  paused: string | null;
  as_of: { build: string; rosters: string };
  week: number;
  attribution: string;
  court?: Court | null;
  court_pending?: boolean;
  created_at?: string;
};

export type Evidence = { id: string; label: string; value: string | number };
export type Argument = { text: string; evidence: Evidence[] };
export type Court = {
  for: Argument[];
  against: Argument[];
  rationale: Argument[];
  notice: string | null;
};

export type Team = { roster_id: number; name: string; players: Player[] };
export type League = {
  league_id: string;
  name: string;
  season: string;
  week: number;
  teams: Team[];
  rulings_saved: number;
  as_of: { build: string; rosters: string };
  warnings: string[];
};

export type Status = { build_id: string | null; as_of: string | null; stale: boolean; age_h?: number };

export class ApiError extends Error {
  constructor(public status: number, message: string, public retry = false) {
    super(message);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    credentials: "same-origin",
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = body.detail ?? body.error ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, msg, Boolean(body.retry));
  }
  return body as T;
}

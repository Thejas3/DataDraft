import type { Player } from "./api";
import { signed } from "./format";

export type WaiverPick = { add: Player; drop: Player | null; status: "waivers" | "free agent";
  delta: number; per_week: Record<string, number>; nflverse_match: boolean | null };

/** D44: a one-line reason from a fixed template over the per-week gains (never LLM). */
export function reason(p: WaiverPick): string {
  const weeks = Object.entries(p.per_week).map(([w, v]) => [Number(w), v] as const);
  const up = weeks.filter(([, v]) => v > 0.05).map(([w]) => w);
  if (!up.length) return "Small gain spread across the season";
  const best = weeks.reduce((a, b) => (b[1] > a[1] ? b : a));
  const span = up.length === weeks.length ? "every remaining week"
    : `${up.length} of ${weeks.length} weeks (wk ${up[0]}–${up[up.length - 1]})`;
  return `Starts for you in ${span}; best in wk ${best[0]} (${signed(best[1])})`;
}


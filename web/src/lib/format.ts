import type { Verdict } from "./api";

const MINUS = "−";

/** D37: always signed, one decimal, with a unit. "+6.4 pts/wk", "−2.1 pts/wk". */
export function signed(x: number, unit = ""): string {
  const v = Math.round(x * 10) / 10;
  const s = v > 0 ? `+${v.toFixed(1)}` : v < 0 ? `${MINUS}${Math.abs(v).toFixed(1)}` : "0.0";
  return unit ? `${s} ${unit}` : s;
}

/** What a screen reader should say for a signed number. */
export function spoken(x: number, unit = "points per week"): string {
  const v = Math.round(x * 10) / 10;
  const word = v > 0 ? "plus " : v < 0 ? "minus " : "";
  return `${word}${Math.abs(v).toFixed(1)} ${unit}`;
}

export const VERDICTS: Record<Verdict, { icon: string; word: string; token: string }> = {
  ACCEPT: { icon: "✓", word: "Accept", token: "accept" },
  COUNTER: { icon: "⇄", word: "Counter", token: "counter" },
  "TOSS-UP": { icon: "≈", word: "Toss-up", token: "tossup" },
  REJECT: { icon: "✕", word: "Reject", token: "reject" },
  INVALID: { icon: "!", word: "Invalid", token: "invalid" },
  UNSUPPORTED: { icon: "∅", word: "Unsupported", token: "unsupported" },
};

export function names(ps: { name: string }[]): string {
  return ps.map((p) => p.name).join(", ");
}

/** "2026-11-03T06:32Z" -> "Nov 3, 6:32 AM" in the viewer's zone. */
export function when(iso: string | null | undefined): string {
  if (!iso) return "unknown";
  const d = new Date(iso.replace("Z", ":00Z"));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function pos(p: { positions: string[] }): string {
  return p.positions.join("/") || "—";
}

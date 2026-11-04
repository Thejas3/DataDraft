// The ruling card (D40), rendered by next/og (satori: flexbox and a CSS subset only).
// Content budget: the trade, the verdict, the deltas, one FOR and one AGAINST line, and
// the footer. Text is passed as JSX children, never as markup (D8).
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { Ruling } from "./api";
import { names, signed, VERDICTS } from "./format";

const dir = join(process.cwd(), "assets/fonts");
const load = (f: string) => readFile(join(dir, f));
export const fontsReady = Promise.all([
  load("stamp-800.ttf"), load("display-800.ttf"), load("display-700.ttf"), load("body-400.ttf"), load("body-600.ttf"),
]).then(([stamp, d8, d7, b4, b6]) => [
  { name: "Stamp", data: stamp, weight: 800 as const, style: "normal" as const },
  { name: "Display", data: d8, weight: 800 as const, style: "normal" as const },
  { name: "Display", data: d7, weight: 700 as const, style: "normal" as const },
  { name: "Body", data: b4, weight: 400 as const, style: "normal" as const },
  { name: "Body", data: b6, weight: 600 as const, style: "normal" as const },
]);

const NAVY = "#0E1726", PAPER = "#F7F7F5", GOLD = "#C9A24A", GAIN = "#6FCF97", LOSS = "#F2878A", MUTED = "#C7CCD6";

export function stampColor(r: Ruling): string {
  if (r.verdict === "ACCEPT" || r.verdict === "COUNTER") return GAIN;
  if (r.verdict === "REJECT") return LOSS;
  return PAPER;
}

/** Verdict icons as strokes: no font has all of ✓ ⇄ ≈ ✕ ! ∅, and satori would try to
 *  fetch missing glyphs over the network at render time. */
export function VerdictIcon({ verdict, size, color }: { verdict: Ruling["verdict"]; size: number; color: string }) {
  const paths: Record<Ruling["verdict"], string[]> = {
    ACCEPT: ["M4 13 L10 19 L20 5"],
    REJECT: ["M5 5 L19 19", "M19 5 L5 19"],
    COUNTER: ["M3 8 H19", "M15 4 L19 8 L15 12", "M21 16 H5", "M9 12 L5 16 L9 20"],
    "TOSS-UP": ["M3 9 C7 5 10 13 14 9 C17 6 19 7 21 9", "M3 16 C7 12 10 20 14 16 C17 13 19 14 21 16"],
    INVALID: ["M12 3 V15", "M12 20 V21"],
    UNSUPPORTED: ["M12 4 A8 8 0 1 0 12.01 4", "M5 19 L19 5"],
  };
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2.6}
         strokeLinecap="round" strokeLinejoin="round">
      {paths[verdict].map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}

export function cardAlt(r: Ruling): string {
  const t = r.trade;
  const v = VERDICTS[r.verdict].word;
  return t ? `Ruling: ${v}. ${names(t.give)} for ${names(t.get)}. ${signed(t.me.delta, "points per week")} for you, ${signed(t.them.delta)} for them.`
    : `Ruling: ${v}.`;
}

export function Card({ r, wide = false }: { r: Ruling; wide?: boolean }) {
  const t = r.trade;
  const v = VERDICTS[r.verdict];
  const pro = r.court?.for?.[0]?.text;
  const con = r.court?.against?.[0]?.text;
  const s = wide ? 0.62 : 1; // the 1200x630 og:image keeps the same hierarchy, smaller
  const date = (r.created_at ?? r.as_of.build ?? "").slice(0, 10);
  return (
    <div style={{ width: "100%", height: "100%", display: "flex", background: NAVY, color: PAPER, padding: 30 * s, fontFamily: "Body" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", border: `2px solid ${GOLD}`, borderRadius: 6, padding: `${56 * s}px ${64 * s}px ${40 * s}px` }}>
        <div style={{ fontFamily: "Display", fontWeight: 700, fontSize: 30 * s, letterSpacing: 4, color: GOLD }}>
          {`OFFICIAL RULING · WEEK ${r.week}`}
        </div>
        {t && (
          <div style={{ display: "flex", flexDirection: "column", marginTop: 28 * s, fontSize: 40 * s, fontWeight: 600, lineHeight: 1.25 }}>
            <span>{`${names(t.give)} → ${names(t.get)}`}</span>
            <span style={{ fontSize: 28 * s, fontWeight: 400, color: MUTED, marginTop: 8 }}>{`${t.me.team} · ${t.them.team}`}</span>
          </div>
        )}
        <div style={{ display: "flex", marginTop: 56 * s }}>
          <div style={{ display: "flex", alignItems: "center", fontFamily: "Stamp", fontWeight: 800, fontSize: 168 * s, lineHeight: 1,
                        color: stampColor(r), border: `${6 * s}px solid ${stampColor(r)}`, padding: `${18 * s}px ${36 * s}px ${6 * s}px`, transform: "rotate(-2.5deg)" }}>
            <div style={{ display: "flex", marginRight: 24 * s }}><VerdictIcon verdict={r.verdict} size={120 * s} color={stampColor(r)} /></div>
            <span>{v.word.toUpperCase()}</span>
          </div>
        </div>
        {t && (
          <div style={{ display: "flex", alignItems: "baseline", marginTop: 48 * s, fontFamily: "Display", fontWeight: 800, fontSize: 64 * s }}>
            <span style={{ color: t.me.delta >= 0 ? GAIN : LOSS }}>{signed(t.me.delta)}</span>
            <span style={{ fontFamily: "Body", fontWeight: 600, fontSize: 28 * s, color: MUTED, margin: `0 ${24 * s}px 0 ${12 * s}px` }}>pts/wk you</span>
            <span>{signed(t.them.delta)}</span>
            <span style={{ fontFamily: "Body", fontWeight: 600, fontSize: 28 * s, color: MUTED, marginLeft: 12 * s }}>them</span>
          </div>
        )}
        {!t && r.reason && <div style={{ display: "flex", marginTop: 40 * s, fontSize: 36 * s }}>{r.reason}</div>}
        {!wide && (
          <div style={{ display: "flex", flexDirection: "column", marginTop: 56, fontSize: 30, lineHeight: 1.35, color: "#DDE1E8" }}>
            {pro && <div style={{ display: "flex" }}><b style={{ fontFamily: "Display", fontWeight: 800, color: PAPER, marginRight: 16, letterSpacing: 2 }}>FOR</b><span>{pro}</span></div>}
            {con && <div style={{ display: "flex", marginTop: 18 }}><b style={{ fontFamily: "Display", fontWeight: 800, color: PAPER, marginRight: 16, letterSpacing: 2 }}>AGAINST</b><span>{con}</span></div>}
          </div>
        )}
        <div style={{ marginTop: "auto", display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: `1px solid ${GOLD}`, paddingTop: 18 * s, fontSize: 22 * s, color: MUTED }}>
          <span style={{ fontFamily: "Display", fontWeight: 800, fontSize: 40 * s, color: PAPER }}>DataDraft</span>
          <span>{`${r.attribution} · ${date}`}</span>
        </div>
      </div>
    </div>
  );
}

const API = process.env.DATADRAFT_API_URL ?? "http://127.0.0.1:8000";

export async function publicRuling(slug: string): Promise<Ruling | null> {
  const res = await fetch(`${API}/api/public/rulings/${encodeURIComponent(slug)}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

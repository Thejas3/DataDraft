"use client";

import { useEffect, useState } from "react";
import type { Verdict } from "@/lib/api";
import { signed, spoken, VERDICTS } from "@/lib/format";
import { useReducedMotion } from "@/lib/hooks";

/** The one authored moment: the stamp lands (320 ms), then deltas count up (700 ms). */
export function Stamp({ verdict }: { verdict: Verdict }) {
  const v = VERDICTS[verdict];
  return (
    <div className="stamp land" role="img" aria-label={`Verdict: ${v.word}`}>
      <span className="ico" aria-hidden="true">{v.icon}</span>
      <span aria-hidden="true">{v.word.toUpperCase()}</span>
    </div>
  );
}

export function CountUp({ value, unit = "pts/wk" }: { value: number; unit?: string }) {
  const reduced = useReducedMotion();
  const [progress, setProgress] = useState(0); // 0..1, only ever set inside frames
  useEffect(() => {
    if (reduced) return;
    let frame = 0;
    const start = performance.now() + 320; // after the stamp lands
    const tick = (t: number) => {
      const k = Math.min(1, Math.max(0, (t - start) / 700));
      setProgress(k);
      if (k < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, reduced]);
  const shown = reduced ? value : value * (1 - Math.pow(1 - progress, 3));
  return (
    <>
      <span aria-hidden="true">{signed(shown)}</span>
      <small aria-hidden="true">{unit}</small>
      <span className="sr-only">{spoken(value)}</span>
    </>
  );
}

export function verdictClass(v: Verdict): string {
  return `v-${VERDICTS[v].token}`;
}

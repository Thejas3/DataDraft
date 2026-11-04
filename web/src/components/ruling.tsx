"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { Argument, Court, Evidence, Ruling, TradeOut } from "@/lib/api";
import { names, signed, spoken, when } from "@/lib/format";
import { CountUp, Stamp, verdictClass } from "./verdict";

type Props = {
  ruling: Ruling;
  court: Court | null; // null while the court is still arguing (D30)
  courtError?: string | null;
  onCopy?: (text: string) => void;
  onShare?: () => void;
  publicView?: boolean;
};

/** D27 reading order: summary, verdict band, action row, FOR | AGAINST | evidence. */
export function RulingView({ ruling, court, courtError, onCopy, onShare, publicView }: Props) {
  const r = ruling;
  const [side, setSide] = useState<"for" | "against">("for");
  const [hl, setHl] = useState<string | null>(null);
  const [sheet, setSheet] = useState<Evidence | null>(null);
  const rail = useRef<HTMLDivElement>(null);
  const shownTrade = r.trade;
  const terminal = r.verdict === "INVALID" || r.verdict === "UNSUPPORTED";

  const pick = (e: Evidence) => {
    if (window.matchMedia("(max-width: 1023px)").matches) { setSheet(e); return; }
    setHl(e.id);
    rail.current?.querySelector(`[data-ev="${e.id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    window.setTimeout(() => setHl((cur) => (cur === e.id ? null : cur)), 2000);
  };
  const evidence = court ? uniqueEvidence(court) : [];

  return (
    <article className="court" aria-labelledby="ruling-h">
      <div className="summary">
        <span id="ruling-h">
          {shownTrade ? <>You send <b>{names(shownTrade.give)}</b> for <b>{names(shownTrade.get)}</b> from {shownTrade.them.team}</>
            : "Trade ruling"}
        </span>
        {!publicView && <Link href="/court">Edit</Link>}
      </div>

      <div className={`band ${verdictClass(r.verdict)}`}>
        <Stamp verdict={r.verdict} />
        {r.paused && <p className="notice n-warn" style={{ marginTop: 24 }}>{r.paused}</p>}
        {terminal ? (
          <p className="notice n-info" style={{ marginTop: 24 }}>{r.reason}</p>
        ) : shownTrade && (
          <Deltas trade={shownTrade} />
        )}
        <CaveatLine ruling={r} />
      </div>

      {!terminal && !publicView && <Actions ruling={r} onCopy={onCopy} onShare={onShare} />}

      {!terminal && (
        <>
          <div className="segmented" role="group" aria-label="Show arguments">
            <button aria-pressed={side === "for"} onClick={() => setSide("for")}>For</button>
            <button aria-pressed={side === "against"} onClick={() => setSide("against")}>Against</button>
          </div>
          <div className="cols">
            <Column title="For" args={court?.for} loading={!court && !courtError} hidden={side !== "for"} onPick={pick} hl={hl} />
            <Column title="Against" args={court?.against} loading={!court && !courtError} hidden={side !== "against"} onPick={pick} hl={hl} />
            <aside className="col rail" ref={rail} aria-label="Evidence">
              <h3>Evidence</h3>
              {!court && !courtError && [0, 1, 2].map((i) => <div key={i} className="skel" />)}
              {evidence.map((e) => (
                <div key={e.id} data-ev={e.id} className={`ev${hl === e.id ? " hl" : ""}`}
                     onMouseEnter={() => setHl(e.id)} onMouseLeave={() => setHl(null)}>
                  <div>{e.label}: <b>{String(e.value)}</b></div>
                  <div className="meta">{e.id} · DataDraft engine · {when(r.as_of.build)}</div>
                </div>
              ))}
            </aside>
          </div>
          {court?.rationale?.length ? (
            <div className="col" style={{ borderTop: "1px solid var(--hairline)" }}>
              <h3>Why</h3>
              {court.rationale.map((a, i) => <p key={i} style={{ margin: "8px 0" }}><ArgText a={a} onPick={pick} /></p>)}
            </div>
          ) : null}
          {(court?.notice || courtError) && (
            <p className="notice n-warn" style={{ margin: 24 }}>{court?.notice ?? courtError}</p>
          )}
        </>
      )}
      {sheet && (
        <div className="sheet" role="dialog" aria-modal="true" aria-label={`Evidence ${sheet.id}`}>
          <p className="mono slate" style={{ margin: 0 }}>{sheet.id} · DataDraft engine · {when(r.as_of.build)}</p>
          <p style={{ fontSize: 18 }}>{sheet.label}: <b>{String(sheet.value)}</b></p>
          <button className="btn btn-secondary" onClick={() => setSheet(null)} autoFocus>Close</button>
        </div>
      )}
    </article>
  );
}

function Deltas({ trade }: { trade: TradeOut }) {
  const me = trade.me.delta;
  return (
    <div className="deltas">
      <div className={`delta ${me >= 0 ? "gain" : "loss"}`}>
        <CountUp value={me} />
        <small aria-hidden="true">your lineup</small>
      </div>
      <div className="delta them" style={{ color: "var(--slate)" }}>
        <span aria-hidden="true">{signed(trade.them.delta)}</span>
        <span className="sr-only">{spoken(trade.them.delta)} for them</span>
        <small aria-hidden="true">{trade.them.team}: they likely say {trade.they_likely}</small>
      </div>
    </div>
  );
}

/** D28: data times, the single most severe caveat, and every caveat under Details. */
function CaveatLine({ ruling }: { ruling: Ruling }) {
  return (
    <div className="caveat">
      Data as of {when(ruling.as_of.build)} · rosters {when(ruling.as_of.rosters)}
      {ruling.caveat && <> · {ruling.caveat}</>}
      {ruling.caveats.length > 0 && (
        <details>
          <summary>Details</summary>
          <ul>{ruling.caveats.map((c, i) => <li key={i}>{c.text}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

/** D31: what the action row offers depends on the verdict. */
function Actions({ ruling, onCopy, onShare }: Pick<Props, "ruling" | "onCopy" | "onShare">) {
  const r = ruling;
  if (r.verdict === "COUNTER" && r.counter) {
    const c = r.counter;
    return (
      <div className="counter-block">
        <h3 style={{ marginBottom: 8 }}>Ask for {names(c.get)} instead</h3>
        <p style={{ margin: "0 0 12px" }}>
          You send {names(c.give)}. That&apos;s {signed(c.me.delta, "pts/wk")} for you and {signed(c.them.delta, "pts/wk")} for them.
        </p>
        <div className="row">
          {r.copy_dm && <button className="btn btn-primary" onClick={() => onCopy?.(r.copy_dm!)}>Copy DM</button>}
          <button className="btn btn-secondary" onClick={onShare}>Share card</button>
        </div>
        {r.copy_dm && <p className="slate small" style={{ marginBottom: 0 }}>{r.copy_dm}</p>}
      </div>
    );
  }
  return (
    <>
      <div className="actions">
        {r.copy_dm ? <button className="btn btn-primary" onClick={() => onCopy?.(r.copy_dm!)}>Copy DM</button>
          : <span className="slate">No better version found.</span>}
        <button className="btn btn-secondary" onClick={onShare}>Share card</button>
      </div>
      {r.copy_dm && <p className="dm-preview">{r.copy_dm}</p>}
    </>
  );
}

function Column({ title, args, loading, hidden, onPick, hl }: {
  title: string; args?: Argument[]; loading: boolean; hidden: boolean;
  onPick: (e: Evidence) => void; hl: string | null;
}) {
  return (
    <section className={`col${hidden ? " hidden-phone" : ""}`} aria-label={title} aria-busy={loading}>
      <h3>{title}</h3>
      {loading ? (
        <>
          <p className="slate small" style={{ margin: 0 }}>Building the case…</p>
          {[0, 1, 2].map((i) => <div key={i} className="skel" style={{ height: 40 }} />)}
        </>
      ) : (
        <ul>
          {(args ?? []).map((a, i) => (
            <li key={i} className={a.evidence.some((e) => e.id === hl) ? "hl" : undefined}><ArgText a={a} onPick={onPick} /></li>
          ))}
          {args && args.length === 0 && <li className="slate">Nothing to add.</li>}
        </ul>
      )}
    </section>
  );
}

function ArgText({ a, onPick }: { a: Argument; onPick: (e: Evidence) => void }) {
  return (
    <>
      {a.text}
      {a.evidence.map((e) => (
        <button key={e.id} className="chip" onClick={() => onPick(e)} title={e.label}
                aria-label={`Evidence ${e.id}: ${e.label}`}>
          {e.id}
        </button>
      ))}
    </>
  );
}

function uniqueEvidence(c: Court): Evidence[] {
  const seen = new Map<string, Evidence>();
  for (const a of [...c.for, ...c.against, ...c.rationale]) for (const e of a.evidence) seen.set(e.id, e);
  return [...seen.values()].sort((x, y) => Number(x.id.slice(1)) - Number(y.id.slice(1)));
}

/** Copy to the clipboard, or fall back to a selectable prompt-free textarea copy. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function useCourt(slug: string, initial: Court | null | undefined, enabled: boolean) {
  const [court, setCourt] = useState<Court | null>(initial ?? null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled || court) return;
    let gone = false;
    fetch(`/api/rulings/${slug}/court`, { method: "POST", credentials: "same-origin" })
      .then(async (res) => {
        const body = await res.json();
        if (!res.ok) throw new Error(body.detail ?? body.error ?? "Arguments unavailable.");
        if (!gone) setCourt(body);
      })
      .catch((e) => !gone && setError(`Arguments unavailable (${e.message}). The ruling and numbers are unaffected.`));
    return () => { gone = true; };
  }, [slug, enabled, court]);
  return { court, error };
}

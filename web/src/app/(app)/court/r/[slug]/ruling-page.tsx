"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useLeague } from "@/components/league";
import { copyText, RulingView, useCourt } from "@/components/ruling";
import type { Ruling } from "@/lib/api";
import { useApi } from "@/lib/hooks";

export function RulingPage({ slug }: { slug: string }) {
  const { toast, announce } = useLeague();
  const { data, error } = useApi<Ruling>(`/api/rulings/${slug}`);
  const wants = Boolean(data?.trade) && data?.verdict !== "INVALID" && data?.verdict !== "UNSUPPORTED";
  const { court, error: courtError } = useCourt(slug, data?.court, wants);

  useEffect(() => { if (court && !data?.court) announce("Arguments loaded"); }, [court, data, announce]);

  if (error) return <p className="notice n-err" role="alert">{error.message}</p>;
  if (!data) return <><div className="skel" style={{ height: 120 }} /><div className="skel" /></>;

  return (
    <>
      <RulingView
        ruling={data}
        court={wants ? court : { for: [], against: [], rationale: [], notice: null }}
        courtError={courtError}
        onCopy={async (t) => toast((await copyText(t)) ? "DM copied: paste it in Sleeper" : "Copy failed: select the DM text below")}
        onShare={async () => {
          const url = `${location.origin}/c/${slug}`;
          toast((await copyText(url)) ? "Card link copied" : url);
        }}
      />
      <p className="slate small" style={{ marginTop: 16 }}>
        Saved · <Link href={`/court/r/${slug}`}>view later</Link> · <Link href={`/c/${slug}`}>public card</Link>
      </p>
    </>
  );
}

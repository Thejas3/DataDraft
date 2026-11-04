"use client";

import { RulingView } from "@/components/ruling";
import type { Ruling } from "@/lib/api";

export function PublicRuling({ ruling }: { ruling: Ruling }) {
  const empty = { for: [], against: [], rationale: [], notice: null };
  return <RulingView ruling={ruling} court={ruling.court ?? empty} publicView />;
}

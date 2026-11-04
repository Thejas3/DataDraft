import { Suspense } from "react";
import { TradeEntry } from "./entry";

export const metadata = { title: "Trade Court" };

export default function CourtPage() {
  return (
    <Suspense>
      <TradeEntry />
    </Suspense>
  );
}

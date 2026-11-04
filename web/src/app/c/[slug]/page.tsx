import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { PublicRuling } from "./public-ruling";
import { cardAlt, publicRuling } from "@/lib/card";
import { VERDICTS, names } from "@/lib/format";

// D34: public, noindex, read-only for one ruling. No app nav, no other league data.
export async function generateMetadata(props: PageProps<"/c/[slug]">): Promise<Metadata> {
  const { slug } = await props.params;
  const r = await publicRuling(slug);
  if (!r) return { title: "Ruling not found", robots: { index: false } };
  const title = r.trade ? `${VERDICTS[r.verdict].word}: ${names(r.trade.give)} for ${names(r.trade.get)}` : VERDICTS[r.verdict].word;
  return { title, description: cardAlt(r), robots: { index: false, follow: false } };
}

export default async function CardPage(props: PageProps<"/c/[slug]">) {
  const { slug } = await props.params;
  const r = await publicRuling(slug);
  if (!r) notFound();
  return (
    <main id="main">
      <div className="wrap">
        <p className="wordmark" style={{ margin: "24px 0 40px" }}>DataDraft</p>
        <div className="cardpage">
          {/* eslint-disable-next-line @next/next/no-img-element -- generated PNG, fixed size */}
          <img src={`/c/${slug}/card.png`} width={1080} height={1350} alt={cardAlt(r)} />
          <PublicRuling ruling={{ ...r, slug, caveats: [], caveat: null, copy_dm: null, paused: null, band: 1 }} />
        </div>
      </div>
      <footer className="site"><div className="wrap">Made with DataDraft · ask your commissioner for access · {r.attribution}</div></footer>
    </main>
  );
}

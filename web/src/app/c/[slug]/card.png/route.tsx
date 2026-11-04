import { ImageResponse } from "next/og";
import { Card, fontsReady, publicRuling } from "@/lib/card";

export async function GET(_req: Request, ctx: RouteContext<"/c/[slug]/card.png">) {
  const { slug } = await ctx.params;
  const r = await publicRuling(slug);
  if (!r) return new Response("This ruling doesn't exist or was removed.", { status: 404 });
  return new ImageResponse(<Card r={r} />, {
    width: 1080, height: 1350, fonts: await fontsReady,
    headers: { "X-Robots-Tag": "noindex", "Cache-Control": "public, max-age=3600" },
  });
}

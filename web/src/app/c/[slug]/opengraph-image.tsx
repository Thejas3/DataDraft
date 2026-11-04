import { ImageResponse } from "next/og";
import { Card, fontsReady, publicRuling } from "@/lib/card";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "A DataDraft trade ruling";

export default async function Image(props: { params: Promise<{ slug: string }> }) {
  const { slug } = await props.params;
  const r = await publicRuling(slug);
  if (!r) return new Response("Not found", { status: 404 });
  return new ImageResponse(<Card r={r} wide />, { ...size, fonts: await fontsReady });
}

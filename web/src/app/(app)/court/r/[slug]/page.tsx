import { RulingPage } from "./ruling-page";

export const metadata = { title: "Ruling" };

export default async function Page(props: PageProps<"/court/r/[slug]">) {
  const { slug } = await props.params;
  return <RulingPage slug={slug} />;
}

import { Profile } from "./profile";

export const metadata = { title: "Player" };

export default async function Page(props: PageProps<"/players/[id]">) {
  const { id } = await props.params;
  return <Profile id={id} />;
}

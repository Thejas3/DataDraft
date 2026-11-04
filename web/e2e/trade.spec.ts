import { expect, test } from "@playwright/test";

const PASS = "e2e-passphrase";

test("paste a trade, get a ruling with cited arguments, share the card", async ({ page, browser, context }, info) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});

  // Gate: unauthenticated visits land on the passphrase form.
  await page.goto("/court");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("League passphrase").fill("wrong");
  await page.getByRole("button", { name: "Enter" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "That's not it." })).toBeVisible();
  await expect(page.getByLabel("League passphrase")).toHaveValue("wrong"); // field keeps its value
  await page.getByLabel("League passphrase").fill(PASS);
  await page.getByRole("button", { name: "Enter" }).click();
  await expect(page).toHaveURL(/\/court/);

  // Find the counterparty from the API (team names in the fixture are anonymized).
  const league = await page.evaluate(() => fetch("/api/leagues/fixture").then((r) => r.json()));
  const owner = (name: string) =>
    league.teams.find((t: { players: { name: string }[] }) => t.players.some((p) => p.name === name));
  const mine = owner("Marvin Harrison Jr.");
  const theirs = owner("MarShawn Lloyd");

  await page.getByLabel("Which team is yours?").selectOption(String(mine.roster_id));
  await page.getByRole("button", { name: /Marvin Harrison Jr\./ }).click();
  await page.getByRole("button", { name: /Dalton Kincaid/ }).click();
  await page.getByLabel("Trade with").selectOption(String(theirs.roster_id));
  await page.getByRole("button", { name: /MarShawn Lloyd/ }).click();
  await page.getByRole("button", { name: "Evaluate" }).click();

  // The verdict and numbers arrive first; the court's arguments stream in after (D30).
  await expect(page).toHaveURL(/\/court\/r\//);
  await expect(page.getByRole("img", { name: "Verdict: Reject" })).toBeVisible();
  await expect(page.getByText("they likely say yes")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Arguments loaded" })).toHaveCount(1);
  await expect(page.getByRole("button", { name: /Evidence E2/ }).first()).toBeVisible();

  // No better version found -> no Copy DM, but the card can be shared.
  await page.getByRole("button", { name: "Share card" }).click();
  const slug = page.url().split("/court/r/")[1];

  // A leaguemate opens the public card page with no session.
  const anon = await browser.newContext();
  const pub = await anon.newPage();
  await pub.goto(`/c/${slug}`);
  await expect(pub.getByRole("img", { name: /Ruling: Reject/ })).toBeVisible();
  await expect(pub.getByRole("link", { name: "Edit" })).toHaveCount(0); // read-only
  const png = await pub.request.get(`/c/${slug}/card.png`);
  expect(png.status()).toBe(200);
  expect(png.headers()["content-type"]).toBe("image/png");
  const buf = await png.body();
  expect([buf.readUInt32BE(16), buf.readUInt32BE(20)]).toEqual([1080, 1350]);
  await pub.screenshot({ path: info.outputPath("public-card.png"), fullPage: true });
  await page.screenshot({ path: info.outputPath("ruling.png"), fullPage: true });
  await anon.close();
});

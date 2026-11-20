import path from "node:path";
import { fileURLToPath } from "node:url";
import { type Browser, type Page, expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const SAMPLE = path.resolve(here, "../../tools/fixtures/samples/checkout-broken.har");
const PASSWORD = "a long e2e password";

async function uploadAs(page: Page, name: string) {
  await page.goto("/");
  await page.getByTestId("file-input").setInputFiles({ name, mimeType: "application/json", buffer: (await import("node:fs")).readFileSync(SAMPLE) });
  await expect(page).toHaveURL(/\/analyses\/[0-9a-f-]+$/);
}

async function joinAs(browser: Browser, inviteUrl: string, name: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await page.goto(new URL(inviteUrl).pathname + new URL(inviteUrl).hash);
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel("Choose a password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Join/ }).click();
  await expect(page.getByRole("heading", { name: "Analyse a HAR file" })).toBeVisible();
  return page;
}

const SHOTS = process.env.STILLS_DIR;
const shot = async (p: Page, name: string) => { if (SHOTS) await p.screenshot({ path: `${SHOTS}/${name}.png` }); };

test("agents see and delete only their own files; admins see everyone's", async ({ page, browser }) => {
  const stamp = Date.now();
  await page.goto("/register");
  await page.getByLabel("Work email").fill(`admin-${stamp}@example.com`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByLabel("Team or company name").fill("E2E Files");
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(page.getByRole("heading", { name: "Analyse a HAR file" })).toBeVisible();

  // Invite two agents through the API with the admin's session.
  const token = await page.evaluate(async () => (await (await fetch("/v1/auth/refresh", { method: "POST", credentials: "include" })).json()).access_token as string);
  const invite = async (email: string) =>
    page.evaluate(
      async ([email, token]) =>
        (await (await fetch("/v1/invitations", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ email, role: "agent" }) })).json()).invite_url as string,
      [email, token] as const,
    );
  const alice = await joinAs(browser, await invite(`alice-${stamp}@example.com`), "Alice");
  const bob = await joinAs(browser, await invite(`bob-${stamp}@example.com`), "Bob");
  await uploadAs(alice, "alice.har");
  await uploadAs(bob, "bob.har");

  // Bob sees only his file, and cannot open Alice's.
  await bob.goto("/analyses");
  await expect(bob.getByRole("heading", { name: "Files" })).toBeVisible();
  await expect(bob.getByRole("link", { name: "bob.har" }).first()).toBeVisible();
  await expect(bob.getByRole("link", { name: "alice.har" })).toHaveCount(0);
  await expect(bob.getByRole("radiogroup", { name: "Whose files" })).toHaveCount(0);
  await shot(bob, "files-as-agent");

  // The admin sees both, with who uploaded them.
  await page.goto("/analyses");
  await expect(page.getByRole("link", { name: "alice.har" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "bob.har" }).first()).toBeVisible();
  await page.waitForTimeout(800);
  await shot(page, "files-as-admin");
  if (SHOTS) {
    await page.goto("/settings");
    await expect(page.getByRole("button", { name: "Save settings" })).toBeVisible();
    await page.waitForTimeout(1200);
    await shot(page, "settings");
  }

  // Alice deletes her file from the analysis page; it disappears for the admin too.
  await alice.goto("/analyses");
  await alice.getByRole("link", { name: "alice.har" }).first().click();
  await alice.getByRole("button", { name: "Delete" }).click();
  const ask = alice.getByRole("group", { name: /Delete alice\.har\?/ });
  await expect(ask).toBeVisible();
  await shot(alice, "delete-confirm");
  await ask.getByRole("button", { name: "Delete" }).click();
  await expect(alice).toHaveURL(/\/analyses$/);
  await expect(alice.getByText("Deleted alice.har.")).toBeVisible();
  await page.goto("/analyses");
  await expect(page.getByRole("link", { name: "bob.har" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "alice.har" })).toHaveCount(0);
});

import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const SAMPLE = path.resolve(here, "../../tools/fixtures/samples/checkout-broken.har");

test("upload a HAR, read the findings, copy the summary, inspect a redacted request", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill("a long e2e password");
  await page.getByLabel("Team or company name").fill("E2E Support");
  await page.getByRole("button", { name: "Create organisation" }).click();
  await expect(page.getByRole("heading", { name: "Analyse a HAR file" })).toBeVisible();

  await page.getByTestId("file-input").setInputFiles(SAMPLE);
  await expect(page).toHaveURL(/\/analyses\/[0-9a-f-]+$/);
  await expect(page.getByTestId("likely-cause")).toContainText("had expired");
  await expect(page.getByTestId("redaction-sentence")).toContainText("Removed 1 token");
  await expect(page.getByTestId("finding").first()).toContainText("R001");

  await page.getByRole("button", { name: "Copy for ticket" }).click();
  await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  expect(copied).toContain("**Likely cause:**");
  expect(copied).not.toMatch(/eyJ[A-Za-z0-9_-]+\.eyJ/); // no token in the ticket text

  await page.getByTestId("finding").filter({ hasText: "R002" }).getByRole("button", { name: /^Show/ }).click();
  const detail = page.getByRole("complementary", { name: /Request \d+/ });
  await expect(detail).toBeVisible();
  await expect(detail.locator("mark").first()).toHaveText(/\[REDACTED:[0-9a-f]{8}\]/);
  await expect(detail).toContainText("expired before this request");

  await page.getByRole("link", { name: "History" }).click();
  await expect(page.getByRole("link", { name: "checkout-broken.har" })).toBeVisible();
});

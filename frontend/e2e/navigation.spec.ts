import { expect, test } from "@playwright/test";
import { newSession, signIn } from "./helpers";

// [sidebar link, text the page's h1 contains]
const PAGES: Array<[string, string]> = [
  ["Chat", "Chat"],
  ["Quick answer", "Quick answer"],
  ["Agent", "Agent"],
  ["Knowledge graph", "Knowledge graph"],
  ["Upload", "Upload a document"],
  ["Documents", "Documents"],
  ["Inspector", "inspector"],
  ["Workspaces", "Workspaces"],
  ["Chunking lab", "Chunking"],
  ["Retrieval lab", "Retrieval"],
  ["Evaluation", "Evaluation"],
  ["Experiments", "Experiments"],
  ["Dashboard", "Dashboard"],
];

test("the sidebar reaches every page without a full reload", async ({ page }) => {
  const session = await newSession("nav");
  await signIn(page, session);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.evaluate(() => ((window as unknown as { __kfMarker: string }).__kfMarker = "alive"));

  const nav = page.getByRole("navigation", { name: "Main" });
  for (const [link, heading] of PAGES) {
    await nav.getByRole("link", { name: link, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 }).first()).toContainText(heading, { ignoreCase: true });
    await expect(nav.getByRole("link", { name: link, exact: true })).toHaveAttribute("aria-current", "page");
  }
  // client-side navigation: the same page context survived every click
  expect(await page.evaluate(() => (window as unknown as { __kfMarker?: string }).__kfMarker)).toBe("alive");
});

test("every page loads without errors", async ({ page }) => {
  const session = await newSession("console");
  await signIn(page, session);
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(`${page.url()}: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`${page.url()}: ${msg.text()}`);
  });
  for (const path of ["/", "/chat", "/query", "/agent", "/graph", "/upload", "/documents", "/inspector",
    "/workspaces", "/chunking-lab", "/retrieval-lab", "/eval", "/experiments"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
    await page.waitForLoadState("networkidle");
  }
  expect(errors).toEqual([]);
});

import { expect, test } from "@playwright/test";
import { newSession, signIn, uploadViaApi } from "./helpers";

const TEXT = "Northwind Logistics. The Lisbon office opened in 2021 and employs 42 engineers.";

test("upload, duplicate refusal, list and delete", async ({ page }) => {
  const session = await newSession("docs");
  await signIn(page, session);
  await page.goto("/upload");
  await expect(page.getByText(`Uploading to ${session.workspaceName}`).first()).toBeVisible();

  const file = { name: "northwind.txt", mimeType: "text/plain", buffer: Buffer.from(TEXT) };
  await page.locator('input[type="file"]').setInputFiles(file);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText(/status: processed/i)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("1 document").first()).toBeVisible(); // sidebar count updated

  // the same bytes again are refused
  await page.locator('input[type="file"]').setInputFiles(file);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByText(/already in this workspace/)).toBeVisible();

  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Documents" }).click();
  const row = page.getByRole("row", { name: /northwind\.txt/ });
  await expect(row).toBeVisible();
  await expect(row.getByText("processed")).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await row.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("No documents here yet")).toBeVisible();
});

test("the inspector shows the text a file produced", async ({ page }) => {
  const session = await newSession("inspect");
  await uploadViaApi(session, "inspect-me.txt", TEXT);
  await signIn(page, session);
  await page.goto("/inspector");
  await expect(page.getByText(TEXT)).toBeVisible();
});

test("dense retrieval finds an uploaded passage (no LLM call)", async ({ page }) => {
  const session = await newSession("retrieve");
  await uploadViaApi(session, "retrieval.txt", TEXT);
  await signIn(page, session);
  await page.goto("/retrieval-lab");
  await page.locator("textarea").first().fill("How many engineers work in Lisbon?");
  await page.getByRole("button", { name: "Dense", exact: true }).click();
  await page.getByRole("button", { name: /Run Dense Retrieval/ }).click();
  await expect(page.getByText("found by: dense").first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("employs 42 engineers").first()).toBeVisible();
});

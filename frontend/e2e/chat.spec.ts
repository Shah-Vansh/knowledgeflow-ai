import { expect, test } from "@playwright/test";
import { newSession, signIn, uploadViaApi } from "./helpers";

// Calls the real LLM, so it only runs with E2E_LLM=1 (the backend needs GROQ_API_KEY).
test.skip(process.env.E2E_LLM !== "1", "set E2E_LLM=1 to run tests that call the LLM");

test("chat answers from the documents and understands a follow-up", async ({ page }) => {
  const session = await newSession("chat");
  await uploadViaApi(
    session,
    "office.txt",
    "Northwind Logistics. The Lisbon office opened in 2021 and employs 42 engineers. Its manager is Ana Ribeiro."
  );
  await signIn(page, session);
  await page.goto("/chat");
  const box = page.locator("textarea").first();
  await box.fill("Who manages the Lisbon office?");
  await box.press("Enter");
  await expect(page.getByText("Who manages the Lisbon office?").last()).toBeVisible(); // shown at once
  await expect(page.getByText(/Ana Ribeiro/).last()).toBeVisible({ timeout: 90_000 });
  await box.fill("When did it open?");
  await box.press("Enter");
  await expect(page.getByText(/2021/).last()).toBeVisible({ timeout: 90_000 });
});

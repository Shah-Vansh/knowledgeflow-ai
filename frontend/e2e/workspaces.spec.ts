import { expect, test } from "@playwright/test";
import { newSession, signIn } from "./helpers";

test("create a workspace and switch between workspaces from the sidebar", async ({ page }) => {
  const session = await newSession("ws");
  await signIn(page, session);
  await page.goto("/workspaces");
  const name = `E2E Research ${Date.now()}`;
  await page.getByPlaceholder("e.g. Engineering").fill(name);
  await page.getByRole("button", { name: "Create workspace" }).click();

  const switcher = page.locator("#kf-workspace");
  await expect(switcher.locator("option:checked")).toHaveText(name);

  await switcher.selectOption({ label: session.workspaceName });
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Documents" }).click();
  await expect(page.getByText(`Files uploaded to ${session.workspaceName}`)).toBeVisible();
  await page.reload(); // the choice survives a reload
  await expect(switcher.locator("option:checked")).toHaveText(session.workspaceName);
});

test("an owner adds a teammate and changes their role", async ({ page }) => {
  const owner = await newSession("owner");
  const teammate = await newSession("mate");
  await signIn(page, owner);
  await page.goto("/workspaces");

  await expect(page.getByText(`Members of ${owner.workspaceName}`)).toBeVisible();
  await page.getByPlaceholder("teammate@company.com").fill(teammate.email);
  const addForm = page.locator("form").filter({ has: page.getByRole("button", { name: "Add member" }) });
  await addForm.locator("select").selectOption("editor");
  await page.getByRole("button", { name: "Add member" }).click();
  await expect(page.getByText(`${teammate.email} is now an editor.`)).toBeVisible();

  const role = page.getByLabel(`Role of ${teammate.email}`);
  await expect(role).toHaveValue("editor");
  await role.selectOption("viewer");
  await expect(page.getByText(`${teammate.email} is now a viewer.`)).toBeVisible();
  await expect(role).toHaveValue("viewer");
});

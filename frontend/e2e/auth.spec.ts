import { expect, test } from "@playwright/test";
import { newSession, PASSWORD, signIn } from "./helpers";

test("signed-out visitors are sent to sign-in and come back afterwards", async ({ page }) => {
  const session = await newSession("auth");
  await page.goto("/documents");
  await expect(page).toHaveURL(/\/login\?next=%2Fdocuments/);

  await page.getByLabel("Email").fill(session.email);
  await page.getByLabel("Password").fill("not-the-password-1");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid email or password")).toBeVisible();

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/documents$/);
  await expect(page.getByRole("heading", { name: "Documents" })).toBeVisible();
  await expect(page.getByText(session.email)).toBeVisible();
});

test("registering a new account leads to the app (first-workspace screen when needed)", async ({ page }) => {
  const email = `e2e-new-${Date.now()}@kf-e2e.test`;
  await page.goto("/login");
  await page.getByRole("button", { name: "Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  // A later user starts with no workspaces (the very first user owns them all).
  const welcome = page.getByText("Welcome to KnowledgeFlow");
  const dashboard = page.getByRole("heading", { name: "Dashboard" });
  await expect(welcome.or(dashboard)).toBeVisible();
  if (await welcome.isVisible()) {
    await page.getByLabel("Workspace name").fill(`E2E first ${Date.now()}`);
    await page.getByRole("button", { name: "Create workspace" }).click();
  }
  await expect(dashboard).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
});

test("log out clears the session", async ({ page }) => {
  const session = await newSession("logout");
  await signIn(page, session);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL(/\/login/);
  expect(await page.evaluate(() => localStorage.getItem("kf_token"))).toBeNull();
});

test("an off-site ?next= is ignored after sign-in", async ({ page }) => {
  const session = await newSession("next");
  await page.goto("/login?next=//evil.example/steal");
  await page.getByLabel("Email").fill(session.email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/localhost:\d+\/$/);
});

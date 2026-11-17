import { expect, Page, test } from "@playwright/test";
import { newSession, signIn } from "./helpers";

const isDark = (page: Page) => page.evaluate(() => document.documentElement.classList.contains("dark"));

test("theme toggle cycles light, dark and system, and survives a reload", async ({ page }) => {
  const session = await newSession("theme");
  await signIn(page, session);
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const toggle = page.getByRole("button", { name: /^Theme:/ });

  await expect(toggle).toHaveAttribute("data-theme-choice", "system");
  await toggle.click(); // system -> light
  await expect(toggle).toHaveAttribute("data-theme-choice", "light");
  expect(await isDark(page)).toBe(false);

  await toggle.click(); // light -> dark
  await expect(toggle).toHaveAttribute("data-theme-choice", "dark");
  expect(await isDark(page)).toBe(true);
  const sidebar = page.locator("aside").first();
  await expect.poll(() => sidebar.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(19, 25, 38)");

  await page.reload();
  expect(await isDark(page)).toBe(true); // applied before the app renders

  await page.getByRole("button", { name: /^Theme:/ }).click(); // dark -> system (OS is light)
  await expect.poll(() => isDark(page)).toBe(false);
  await page.emulateMedia({ colorScheme: "dark" });
  await expect.poll(() => isDark(page)).toBe(true); // follows the OS live
});

test("the sign-in page follows the system dark theme", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  expect(await isDark(page)).toBe(true);
});

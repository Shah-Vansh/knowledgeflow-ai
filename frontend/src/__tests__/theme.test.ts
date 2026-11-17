import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyTheme,
  getThemeChoice,
  nextThemeChoice,
  resolveTheme,
  setThemeChoice,
  THEME_INIT_SCRIPT,
  THEME_KEY,
} from "@/lib/theme";

function mockSystemDark(dark: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: dark, addEventListener() {}, removeEventListener() {} });
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  mockSystemDark(false);
});

describe("theme", () => {
  it("resolves system to the OS preference", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("light", true)).toBe("light");
  });

  it("cycles light -> dark -> system -> light", () => {
    expect(nextThemeChoice("light")).toBe("dark");
    expect(nextThemeChoice("dark")).toBe("system");
    expect(nextThemeChoice("system")).toBe("light");
  });

  it("defaults to system and ignores junk in storage", () => {
    expect(getThemeChoice()).toBe("system");
    localStorage.setItem(THEME_KEY, "purple");
    expect(getThemeChoice()).toBe("system");
  });

  it("stores the choice and toggles html.dark", () => {
    setThemeChoice("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    setThemeChoice("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    mockSystemDark(true);
    expect(applyTheme("system")).toBe("dark");
  });

  it("the pre-paint script applies the stored or system theme", () => {
    localStorage.setItem(THEME_KEY, "dark");
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    document.documentElement.classList.remove("dark");
    localStorage.setItem(THEME_KEY, "light");
    mockSystemDark(true);
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    localStorage.removeItem(THEME_KEY);
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });
});

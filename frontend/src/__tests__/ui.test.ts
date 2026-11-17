import { describe, expect, it } from "vitest";
import { cx, statusTone } from "@/components/ui";
import { NAV } from "@/components/AppShell";

describe("statusTone", () => {
  it.each([
    ["processed", "success"],
    ["succeeded", "success"],
    ["queued", "brand"],
    ["running", "brand"],
    ["failed", "danger"],
    ["cancelled", "warning"],
    ["FAILED", "danger"],
    [null, "neutral"],
    ["something-new", "neutral"],
  ])("%s -> %s", (status, tone) => {
    expect(statusTone(status as string | null)).toBe(tone);
  });
});

describe("cx", () => {
  it("joins truthy class names only", () => {
    expect(cx("a", false, null, undefined, "b")).toBe("a b");
  });
});

describe("navigation", () => {
  const items = NAV.flatMap((group) => group.items);
  it("lists every page exactly once", () => {
    const hrefs = items.map((i) => i.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
    expect(hrefs.sort()).toEqual(
      ["/", "/agent", "/chat", "/chunking-lab", "/documents", "/eval", "/experiments", "/graph",
       "/inspector", "/query", "/retrieval-lab", "/upload", "/workspaces"].sort()
    );
  });
});

describe("Markdown", () => {
  it("parses paragraphs and lists", async () => {
    const { parseBlocks } = await import("@/components/Markdown");
    const blocks = parseBlocks("Intro line\n\n- one\n- two\n\n1. first\n2) second\nTail");
    expect(blocks.map((b) => b.kind)).toEqual(["p", "ul", "ol", "p"]);
  });

  it("turns **bold**, *italic* and `code` into elements, never raw HTML", async () => {
    const { renderInline } = await import("@/components/Markdown");
    const parts = renderInline("Total **600 EUR** per *year* via `portal` <img src=x onerror=alert(1)>");
    const strings = parts.filter((p) => typeof p === "string").join("");
    expect(strings).toContain("<img src=x onerror=alert(1)>"); // stays plain text
    expect(parts.filter((p) => typeof p !== "string")).toHaveLength(3);
  });
});

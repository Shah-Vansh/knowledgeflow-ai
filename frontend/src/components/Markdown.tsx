/**
 * Renders the small Markdown subset LLM answers use — paragraphs, bullet and
 * numbered lists, **bold**, *italic* and `code` — as React elements.
 * It never injects HTML, so model output can't add scripts, links or images.
 */
import { Fragment, ReactNode } from "react";

const INLINE = /(\*\*[^*\n]+\*\*|__[^_\n]+__|`[^`\n]+`|\*[^*\s][^*\n]*\*|_[^_\s][^_\n]*_)/g;

export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > last) out.push(text.slice(last, start));
    if (token.startsWith("**") || token.startsWith("__")) {
      out.push(<strong key={key++} className="font-semibold text-slate-900">{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("`")) {
      out.push(<code key={key++} className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em]">{token.slice(1, -1)}</code>);
    } else {
      out.push(<em key={key++}>{token.slice(1, -1)}</em>);
    }
    last = start + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] };

export function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of source.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    const last = blocks[blocks.length - 1];
    if (bullet) {
      if (last?.kind === "ul") last.items.push(bullet[1]);
      else blocks.push({ kind: "ul", items: [bullet[1]] });
    } else if (numbered) {
      if (last?.kind === "ol") last.items.push(numbered[1]);
      else blocks.push({ kind: "ol", items: [numbered[1]] });
    } else if (!line.trim()) {
      blocks.push({ kind: "p", lines: [] }); // paragraph break
    } else if (last?.kind === "p" && last.lines.length > 0) {
      last.lines.push(line.replace(/^#{1,6}\s+/, ""));
    } else {
      blocks.push({ kind: "p", lines: [line.replace(/^#{1,6}\s+/, "")] });
    }
  }
  return blocks.filter((b) => (b.kind === "p" ? b.lines.length > 0 : b.items.length > 0));
}

export default function Markdown({ text, className }: { text: string; className?: string }) {
  return (
    <div className={`space-y-2 ${className ?? ""}`}>
      {parseBlocks(text).map((block, i) => {
        if (block.kind === "ul") {
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {block.items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}
            </ul>
          );
        }
        if (block.kind === "ol") {
          return (
            <ol key={i} className="list-decimal space-y-1 pl-5">
              {block.items.map((item, j) => <li key={j}>{renderInline(item)}</li>)}
            </ol>
          );
        }
        return (
          <p key={i}>
            {block.lines.map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                {renderInline(line)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

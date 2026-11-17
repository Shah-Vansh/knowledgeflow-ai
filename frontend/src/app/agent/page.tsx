"use client";

import { useEffect, useState } from "react";
import { useWorkspace } from "@/lib/workspace-context";
import { AgentResponse, askAgent } from "@/lib/agent";
import { Alert, Badge, BadgeTone, Button, Card, Field, PageHeader, cx, inputClass } from "@/components/ui";

const EXAMPLES = [
  "How many PDFs are uploaded?",
  "What is 15% of 240?",
  "List my latest documents",
  "Do I have a file about budget?",
  "How is <entity A> related to <entity B>?",
  "Summarize the main idea of my documents",
];

const ROUTE_TONE: Record<string, BadgeTone> = {
  rag: "brand",
  graph: "success",
  document_search: "warning",
  metadata: "neutral",
  calculator: "success",
};

function RouteBadge({ route }: { route: string }) {
  return (
    <Badge tone={ROUTE_TONE[route] ?? "neutral"} className="font-mono">
      {route}
    </Badge>
  );
}

export default function AgentPage() {
  const { workspaceId, workspace } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setResult(null);
    setError("");
  }, [workspaceId]);

  const ask = async () => {
    if (!question.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      setResult(await askAgent(question.trim(), workspaceId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "The agent request failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agent"
        description="One LLM call decides which tool handles your question: document search (RAG), the knowledge graph, a filename search, library metadata, or a calculator. Tools that can't handle a question hand it back to RAG."
      />

      <Card>
        <div className="space-y-4">
          <Field label={`Ask anything about ${workspace?.name ?? "this workspace"}`}>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask anything about this workspace..."
              rows={2}
              maxLength={1000}
              className={inputClass}
            />
          </Field>

          <div>
            <p className="mb-2 text-xs font-medium text-slate-500">Try an example</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  type="button"
                  onClick={() => setQuestion(example)}
                  className={cx(
                    "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                    question === example
                      ? "border-brand-300 bg-brand-50 text-brand-700"
                      : "border-slate-200 bg-white text-slate-600 hover:border-brand-200 hover:bg-brand-50 hover:text-brand-700"
                  )}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>

          <div className="flex justify-end">
            <Button onClick={ask} disabled={!question.trim()} loading={loading}>
              {loading ? "Thinking…" : "Ask the agent"}
            </Button>
          </div>
        </div>
      </Card>

      {error && <Alert tone="error">{error}</Alert>}

      {result && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card
            className="lg:col-span-2"
            title={
              <span className="flex flex-wrap items-center gap-2">
                <span>Router chose</span>
                <RouteBadge route={result.route} />
                {result.used_route !== result.route && (
                  <>
                    <span className="font-normal text-slate-500">→ answered by</span>
                    <RouteBadge route={result.used_route} />
                  </>
                )}
              </span>
            }
            actions={<span className="text-xs text-slate-500">{result.llm_calls} LLM call(s)</span>}
          >
            <div className="space-y-4">
              {result.route_fallback && (
                <Alert tone="warning">The router&apos;s reply was unusable, so the question went to RAG.</Alert>
              )}
              {result.fallback_to_rag && result.fallback_reason && (
                <Alert tone="warning">
                  The {result.route} tool couldn&apos;t handle this ({result.fallback_reason}), so RAG answered.
                </Alert>
              )}

              <p className="whitespace-pre-wrap text-sm leading-6 text-slate-900">{result.answer}</p>

              {result.sources.length > 0 && (
                <div className="border-t border-slate-100 pt-3">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Sources</p>
                  <div className="flex flex-wrap gap-1.5">
                    {result.sources.map((s) => (
                      <Badge key={`${s.document_id}-${s.page_number ?? "na"}`}>
                        {s.filename}
                        {s.page_number !== null ? ` · p.${s.page_number}` : ""}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {result.graph && result.graph.facts.length > 0 && (
                <div className="border-t border-slate-100 pt-3">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">
                    Graph facts used{" "}
                    <span className="normal-case tracking-normal text-slate-400">
                      ({result.graph.matched_entities.join(", ")})
                    </span>
                  </p>
                  <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-xs">
                    {result.graph.facts.map((f, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-1.5 px-3 py-2">
                        <span className="font-medium text-slate-900">{f.source}</span>
                        <Badge tone="brand">{f.relation}</Badge>
                        <span className="font-medium text-slate-900">{f.target}</span>
                        <span className="ml-auto text-slate-400">
                          {f.filename}
                          {f.page_number !== null ? `, p.${f.page_number}` : ""}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {result.tool_result && (
                <details className="text-xs">
                  <summary className="cursor-pointer font-medium text-slate-600 hover:text-slate-900">Tool result</summary>
                  <pre className="scrollbar-thin mt-2 overflow-x-auto rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-700">
                    {JSON.stringify(result.tool_result, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </Card>

          <Card title="Agent trace" description="Each step the agent took, in order." padded={false}>
            <ol className="divide-y divide-slate-100">
              {result.trace.map((step, i) => (
                <li key={i} className="px-5 py-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono font-medium text-slate-800">
                      {i + 1}. {step.step}
                    </span>
                    <span className="shrink-0 tabular-nums text-slate-400">{Math.round(step.ms)} ms</span>
                  </div>
                  <p className="mt-0.5 text-slate-600">{step.detail}</p>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      )}
    </div>
  );
}

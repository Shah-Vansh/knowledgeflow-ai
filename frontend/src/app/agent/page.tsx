"use client";

import { useEffect, useState } from "react";
import { listWorkspaces, Workspace } from "@/lib/workspaces";
import { AgentResponse, askAgent } from "@/lib/agent";

const EXAMPLES = [
  "How many PDFs are uploaded?",
  "What is 15% of 240?",
  "List my latest documents",
  "Do I have a file about budget?",
  "How is <entity A> related to <entity B>?",
  "Summarize the main idea of my documents",
];

const ROUTE_STYLE: Record<string, string> = {
  rag: "bg-blue-100 text-blue-800",
  graph: "bg-purple-100 text-purple-800",
  document_search: "bg-amber-100 text-amber-800",
  metadata: "bg-teal-100 text-teal-800",
  calculator: "bg-green-100 text-green-800",
};

function RouteBadge({ route }: { route: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${ROUTE_STYLE[route] ?? "bg-gray-100"}`}>
      {route}
    </span>
  );
}

export default function AgentPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AgentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0) setWorkspaceId(list[0].id);
      })
      .catch(() => setError("Could not load workspaces"));
  }, []);

  const ask = async () => {
    if (!question.trim() || workspaceId === null) return;
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
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Agent</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-xl">
        One LLM call decides which tool handles your question: document search (RAG), the knowledge
        graph, a filename search, library metadata, or a calculator. Tools that can&apos;t handle a
        question hand it back to RAG.
      </p>

      <div className="w-full max-w-3xl space-y-4">
        <label className="block text-sm">
          Workspace
          <select
            value={workspaceId ?? ""}
            onChange={(e) => setWorkspaceId(Number(e.target.value))}
            className="block w-full border border-gray-300 rounded p-2 mt-1 bg-white"
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} ({w.document_count})
              </option>
            ))}
          </select>
        </label>

        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask anything about this workspace..."
          rows={2}
          maxLength={1000}
          className="w-full border border-gray-300 rounded-lg p-3 text-sm"
        />

        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              onClick={() => setQuestion(example)}
              className="text-xs border border-gray-300 rounded-full px-3 py-1 bg-white text-gray-600"
            >
              {example}
            </button>
          ))}
        </div>

        <button
          onClick={ask}
          disabled={!question.trim() || workspaceId === null || loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2 disabled:opacity-50"
        >
          {loading ? "Thinking..." : "Ask the agent"}
        </button>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {result && (
          <div className="space-y-3">
            <div className="border border-gray-300 rounded-lg p-4 bg-white space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
                <span>Router chose</span>
                <RouteBadge route={result.route} />
                {result.used_route !== result.route && (
                  <>
                    <span>→ answered by</span>
                    <RouteBadge route={result.used_route} />
                  </>
                )}
                <span className="ml-auto">{result.llm_calls} LLM call(s)</span>
              </div>

              {result.route_fallback && (
                <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
                  The router&apos;s reply was unusable, so the question went to RAG.
                </p>
              )}
              {result.fallback_to_rag && result.fallback_reason && (
                <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">
                  The {result.route} tool couldn&apos;t handle this ({result.fallback_reason}), so RAG answered.
                </p>
              )}

              <p className="whitespace-pre-wrap text-sm">{result.answer}</p>

              {result.sources.length > 0 && (
                <div className="text-xs text-gray-600">
                  <p className="font-medium">Sources</p>
                  <ul className="list-disc list-inside">
                    {result.sources.map((s) => (
                      <li key={`${s.document_id}-${s.page_number ?? "na"}`}>
                        {s.filename}
                        {s.page_number !== null ? ` — page ${s.page_number}` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {result.graph && result.graph.facts.length > 0 && (
                <div className="text-xs text-gray-600">
                  <p className="font-medium">
                    Graph facts used ({result.graph.matched_entities.join(", ")})
                  </p>
                  <ul className="list-disc list-inside">
                    {result.graph.facts.map((f, i) => (
                      <li key={i}>
                        {f.source} —[{f.relation}]→ {f.target}{" "}
                        <span className="text-gray-400">
                          ({f.filename}
                          {f.page_number !== null ? `, p.${f.page_number}` : ""})
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {result.tool_result && (
                <details className="text-xs">
                  <summary className="cursor-pointer text-gray-600">Tool result</summary>
                  <pre className="mt-1 bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto">
                    {JSON.stringify(result.tool_result, null, 2)}
                  </pre>
                </details>
              )}
            </div>

            <div className="border border-gray-300 rounded-lg p-3 bg-white text-xs">
              <p className="font-medium mb-1">Agent trace</p>
              <ol className="space-y-1">
                {result.trace.map((step, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="w-28 shrink-0 font-mono text-gray-700">
                      {i + 1}. {step.step}
                    </span>
                    <span className="flex-1 text-gray-600">{step.detail}</span>
                    <span className="text-gray-400">{Math.round(step.ms)} ms</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}

        <div className="flex justify-between text-sm pt-2">
          <a href="/chat" className="text-blue-600 underline">
            ← Chat
          </a>
          <a href="/graph" className="text-blue-600 underline">
            Knowledge graph →
          </a>
        </div>
      </div>
    </main>
  );
}
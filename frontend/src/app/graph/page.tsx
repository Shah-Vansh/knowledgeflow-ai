"use client";

import { useEffect, useMemo, useState } from "react";
import { listWorkspaces, Workspace } from "@/lib/workspaces";
import { DocumentSummary, listDocuments } from "@/lib/documents";
import { askGraph, buildGraph, BuildReport, getGraph, GraphAnswer, GraphView } from "@/lib/graph";

const TYPE_COLORS: Record<string, string> = {
  PERSON: "#f59e0b",
  ORG: "#3b82f6",
  TECH: "#8b5cf6",
  CONCEPT: "#10b981",
  LOCATION: "#ef4444",
  PRODUCT: "#ec4899",
  EVENT: "#14b8a6",
  OTHER: "#6b7280",
};

const WIDTH = 640;
const HEIGHT = 460;
const MAX_DRAWN_NODES = 30;
const MAX_LABELLED_EDGES = 25;

function GraphDrawing({ graph, highlight }: { graph: GraphView; highlight: Set<string> }) {
  const nodes = graph.nodes.slice(0, MAX_DRAWN_NODES);

  const positions = useMemo(() => {
    const centerX = WIDTH / 2;
    const centerY = HEIGHT / 2;
    const radius = Math.min(WIDTH, HEIGHT) / 2 - 60;
    const map = new Map<number, { x: number; y: number }>();
    nodes.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / Math.max(nodes.length, 1) - Math.PI / 2;
      map.set(node.id, {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      });
    });
    return map;
  }, [nodes]);

  const drawnEdges = graph.edges.filter((e) => positions.has(e.source) && positions.has(e.target));
  const labelEdges = drawnEdges.length <= MAX_LABELLED_EDGES;

  if (nodes.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        No graph yet. Build one from a document below — it is never built automatically.
      </p>
    );
  }

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full border border-gray-200 rounded-lg bg-white"
      role="img"
      aria-label="Knowledge graph"
    >
      {drawnEdges.map((edge) => {
        const from = positions.get(edge.source)!;
        const to = positions.get(edge.target)!;
        return (
          <g key={edge.id}>
            <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke="#cbd5e1" strokeWidth={1.5} />
            {labelEdges && (
              <text
                x={(from.x + to.x) / 2}
                y={(from.y + to.y) / 2}
                fontSize={9}
                textAnchor="middle"
                fill="#64748b"
              >
                {edge.relation}
              </text>
            )}
          </g>
        );
      })}

      {nodes.map((node) => {
        const position = positions.get(node.id)!;
        const radius = Math.min(10 + node.degree * 2, 22);
        const highlighted = highlight.has(node.name.toLowerCase());
        return (
          <g key={node.id}>
            <circle
              cx={position.x}
              cy={position.y}
              r={radius}
              fill={TYPE_COLORS[node.type] ?? TYPE_COLORS.OTHER}
              stroke={highlighted ? "#111827" : "#ffffff"}
              strokeWidth={highlighted ? 3 : 1.5}
            />
            <text
              x={position.x}
              y={position.y + radius + 11}
              fontSize={10}
              textAnchor="middle"
              fill="#111827"
            >
              {node.name.length > 22 ? `${node.name.slice(0, 21)}…` : node.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function GraphPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [graph, setGraph] = useState<GraphView | null>(null);
  const [error, setError] = useState("");

  const [maxChunks, setMaxChunks] = useState(60);
  const [groupSize, setGroupSize] = useState(4);
  const [buildingId, setBuildingId] = useState<number | null>(null);
  const [report, setReport] = useState<BuildReport | null>(null);

  const [question, setQuestion] = useState("");
  const [hops, setHops] = useState(2);
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<GraphAnswer | null>(null);

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0) setWorkspaceId(list[0].id);
      })
      .catch(() => setError("Could not load workspaces"));
  }, []);

  const refresh = (id: number) => {
    getGraph(id).then(setGraph).catch((err) => setError(err instanceof Error ? err.message : "Could not load the graph"));
    listDocuments("processed", id).then(setDocuments).catch(() => {});
  };

  useEffect(() => {
    if (workspaceId === null) return;
    setReport(null);
    setAnswer(null);
    setError("");
    refresh(workspaceId);
  }, [workspaceId]);

  const maxCalls = Math.ceil(maxChunks / groupSize);

  const handleBuild = async (documentId: number) => {
    if (workspaceId === null) return;
    setBuildingId(documentId);
    setError("");
    setReport(null);
    try {
      setReport(await buildGraph(documentId, maxChunks, groupSize));
      refresh(workspaceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build the graph");
    } finally {
      setBuildingId(null);
    }
  };

  const handleAsk = async () => {
    if (!question.trim() || workspaceId === null) return;
    setAsking(true);
    setError("");
    setAnswer(null);
    try {
      setAnswer(await askGraph(question.trim(), workspaceId, hops));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Graph query failed");
    } finally {
      setAsking(false);
    }
  };

  const highlight = new Set((answer?.graph.matched_entities ?? []).map((n) => n.toLowerCase()));
  const nodeNames = new Map((graph?.nodes ?? []).map((n) => [n.id, n.name]));

  return (
    <main className="min-h-screen p-8 flex flex-col items-center">
      <h1 className="text-2xl font-bold mb-2">Knowledge Graph</h1>
      <p className="text-sm text-gray-500 mb-6 text-center max-w-xl">
        Entities and relationships extracted from your documents. Every relationship is stored with
        the exact passage it came from, and nothing is kept unless its names appear in that text.
      </p>

      <div className="w-full max-w-4xl space-y-5">
        <label className="block text-sm">
          Workspace
          <select
            value={workspaceId ?? ""}
            onChange={(e) => setWorkspaceId(Number(e.target.value))}
            className="block w-full border border-gray-300 rounded p-2 mt-1 bg-white"
          >
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>

        {error && <div className="text-red-600 text-sm">{error}</div>}

        {graph && (
          <p className="text-sm text-gray-600">
            {graph.totals.entities} entities · {graph.totals.relationships} relationships ·{" "}
            {graph.totals.documents_with_graph} document(s) with a graph
            {graph.nodes.length > MAX_DRAWN_NODES
              ? ` · drawing the ${MAX_DRAWN_NODES} most connected`
              : ""}
          </p>
        )}

        {graph && <GraphDrawing graph={graph} highlight={highlight} />}

        <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3">
          <h2 className="font-semibold text-sm">Ask the graph</h2>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="e.g. How is <entity A> related to <entity B>?"
            rows={2}
            maxLength={1000}
            className="w-full border border-gray-300 rounded-lg p-2 text-sm"
          />
          <div className="flex items-center gap-3 text-sm">
            <label>
              Hops:{" "}
              <select
                value={hops}
                onChange={(e) => setHops(Number(e.target.value))}
                className="border border-gray-300 rounded p-1"
              >
                {[1, 2, 3].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={handleAsk}
              disabled={!question.trim() || asking || workspaceId === null}
              className="ml-auto bg-blue-600 text-white rounded-lg px-4 py-1.5 text-sm disabled:opacity-50"
            >
              {asking ? "Thinking..." : "Ask"}
            </button>
          </div>

          {answer && (
            <div className="space-y-2 text-sm">
              <p className="whitespace-pre-wrap">{answer.answer}</p>
              <p className="text-xs text-gray-500">
                Mode: {answer.mode}
                {answer.graph.matched_entities.length > 0
                  ? ` · matched: ${answer.graph.matched_entities.join(", ")}`
                  : " · no known entity was named, so this used text retrieval only"}
              </p>
              {answer.graph.facts.length > 0 && (
                <ul className="list-disc list-inside text-xs text-gray-600">
                  {answer.graph.facts.map((f, i) => (
                    <li key={i}>
                      {f.source} —[{f.relation}]→ {f.target}{" "}
                      <span className="text-gray-400">
                        ({f.filename}
                        {f.page_number !== null ? `, p.${f.page_number}` : ""}, hop {f.hop})
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>

        <section className="border border-gray-300 rounded-lg bg-white p-4 space-y-3">
          <h2 className="font-semibold text-sm">Build a graph from a document</h2>
          <p className="text-xs text-gray-500">
            This uses LLM calls (about one per {groupSize} chunks) and never runs automatically.
            Rebuilding replaces that document&apos;s previous graph.
          </p>
          <div className="flex gap-4 text-sm">
            <label>
              Max chunks{" "}
              <input
                type="number"
                min={1}
                max={200}
                value={maxChunks}
                onChange={(e) => setMaxChunks(Number(e.target.value))}
                className="w-20 border border-gray-300 rounded p-1"
              />
            </label>
            <label>
              Chunks per call{" "}
              <input
                type="number"
                min={1}
                max={8}
                value={groupSize}
                onChange={(e) => setGroupSize(Number(e.target.value))}
                className="w-16 border border-gray-300 rounded p-1"
              />
            </label>
          </div>

          {documents.length === 0 && (
            <p className="text-sm text-gray-500">No processed documents in this workspace.</p>
          )}
          {documents.map((d) => (
            <div key={d.id} className="flex items-center justify-between border border-gray-200 rounded p-2 text-sm">
              <span>
                #{d.id} — {d.filename}
              </span>
              <button
                onClick={() => handleBuild(d.id)}
                disabled={buildingId !== null}
                className="border border-blue-600 text-blue-600 rounded px-3 py-1 text-xs disabled:opacity-50"
              >
                {buildingId === d.id ? "Building..." : `Build graph (≤ ${maxCalls} calls)`}
              </button>
            </div>
          ))}

          {report && (
            <div className="text-xs bg-green-50 border border-green-200 rounded p-2 space-y-0.5">
              <p className="font-medium">Built from document #{report.document_id}</p>
              <p>
                {report.entities} entities, {report.relationships} relationships from{" "}
                {report.chunks_processed}/{report.chunks_total} chunks in {report.llm_calls} LLM call(s)
                ({Math.round(report.elapsed_ms / 100) / 10}s)
              </p>
              <p>
                Rejected for not matching the text: {report.dropped_entities} entities,{" "}
                {report.dropped_relations} relationships
                {report.groups_failed > 0 ? ` · ${report.groups_failed} call(s) failed and were skipped` : ""}
                {report.truncated ? " · only the first chunks were processed" : ""}
              </p>
            </div>
          )}
        </section>

        {graph && graph.edges.length > 0 && (
          <section className="border border-gray-300 rounded-lg bg-white p-4">
            <h2 className="font-semibold text-sm mb-2">Relationships</h2>
            <ul className="text-xs text-gray-700 space-y-1 max-h-72 overflow-y-auto">
              {graph.edges.map((edge) => (
                <li key={edge.id}>
                  {nodeNames.get(edge.source)} —[{edge.relation}]→ {nodeNames.get(edge.target)}{" "}
                  <span className="text-gray-400">
                    ({edge.filename ?? "?"}
                    {edge.page_number !== null ? `, p.${edge.page_number}` : ""})
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="flex justify-between text-sm pt-2">
          <a href="/agent" className="text-blue-600 underline">
            ← Agent
          </a>
          <a href="/chat" className="text-blue-600 underline">
            Chat →
          </a>
        </div>
      </div>
    </main>
  );
}
"use client";

import Markdown from "@/components/Markdown";
import { useEffect, useMemo, useState } from "react";
import { useWorkspace } from "@/lib/workspace-context";
import { DocumentSummary, listDocuments } from "@/lib/documents";
import { askGraph, buildGraph, BuildReport, getGraph, GraphAnswer, GraphView } from "@/lib/graph";
import {
  Alert,
  Badge,
  Button,
  ButtonLink,
  Card,
  EmptyState,
  Field,
  Loading,
  PageHeader,
  Stat,
  inputClass,
} from "@/components/ui";
import { GraphIcon } from "@/components/icons";

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
      <EmptyState
        icon={<GraphIcon className="h-8 w-8" />}
        title="No graph yet"
        description="Build one from a document below — it is never built automatically."
      />
    );
  }

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className="w-full rounded-lg bg-white"
      role="img"
      aria-label="Knowledge graph"
    >
      {drawnEdges.map((edge) => {
        const from = positions.get(edge.source)!;
        const to = positions.get(edge.target)!;
        return (
          <g key={edge.id}>
            <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} className="stroke-slate-300" strokeWidth={1.5} />
            {labelEdges && (
              <text
                x={(from.x + to.x) / 2}
                y={(from.y + to.y) / 2}
                fontSize={9}
                textAnchor="middle"
                className="fill-slate-500"
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
              className={highlighted ? "stroke-slate-900" : "stroke-surface"}
              strokeWidth={highlighted ? 3 : 1.5}
            />
            <text
              x={position.x}
              y={position.y + radius + 11}
              fontSize={10}
              textAnchor="middle"
              className="fill-slate-900"
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
  const { workspaceId, workspace } = useWorkspace();
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

  const refresh = (id: number) => {
    getGraph(id).then(setGraph).catch((err) => setError(err instanceof Error ? err.message : "Could not load the graph"));
    listDocuments("processed", id).then(setDocuments).catch(() => {});
  };

  useEffect(() => {
    setGraph(null);
    setDocuments([]);
    setReport(null);
    setAnswer(null);
    setError("");
    refresh(workspaceId);
  }, [workspaceId]);

  const maxCalls = Math.ceil(maxChunks / groupSize);

  const handleBuild = async (documentId: number) => {
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
    if (!question.trim()) return;
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
    <div className="space-y-6">
      <PageHeader
        title="Knowledge graph"
        description={
          <>
            Entities and relationships extracted from the documents in {workspace?.name ?? "this workspace"}. Every
            relationship is stored with the exact passage it came from, and nothing is kept unless its names appear in
            that text.
          </>
        }
      />

      {error && <Alert tone="error">{error}</Alert>}

      {graph ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Stat label="Entities" value={graph.totals.entities} />
          <Stat label="Relationships" value={graph.totals.relationships} />
          <Stat label="Documents with a graph" value={graph.totals.documents_with_graph} />
        </div>
      ) : (
        !error && <Loading label="Loading graph…" />
      )}

      {graph && (
        <Card
          title="Graph"
          description={
            graph.nodes.length > MAX_DRAWN_NODES
              ? `Drawing the ${MAX_DRAWN_NODES} most connected entities.`
              : "Node size reflects how connected an entity is; entities matched by your question are outlined."
          }
        >
          <GraphDrawing graph={graph} highlight={highlight} />
          {graph.nodes.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-slate-100 pt-3">
              {Object.entries(TYPE_COLORS).map(([type, color]) => (
                <span key={type} className="flex items-center gap-1.5 text-xs text-slate-500">
                  <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: color }} />
                  {type}
                </span>
              ))}
            </div>
          )}
        </Card>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card title="Ask the graph" description="Answers using facts reachable from the entities you name.">
          <div className="space-y-4">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. How is <entity A> related to <entity B>?"
              rows={2}
              maxLength={1000}
              aria-label="Question for the graph"
              className={inputClass}
            />
            <div className="flex items-end gap-3">
              <Field label="Hops" className="w-24">
                <select value={hops} onChange={(e) => setHops(Number(e.target.value))} className={inputClass}>
                  {[1, 2, 3].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </Field>
              <Button onClick={handleAsk} disabled={!question.trim()} loading={asking} className="ml-auto">
                {asking ? "Thinking…" : "Ask"}
              </Button>
            </div>

            {answer && (
              <div className="space-y-3 border-t border-slate-100 pt-4">
                <Markdown text={answer.answer} className="text-sm leading-6 text-slate-900" />
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                  <Badge>mode: {answer.mode}</Badge>
                  {answer.graph.matched_entities.length > 0 ? (
                    <>
                      <span>matched</span>
                      {answer.graph.matched_entities.map((name) => (
                        <Badge key={name} tone="brand">
                          {name}
                        </Badge>
                      ))}
                    </>
                  ) : (
                    <span>no known entity was named, so this used text retrieval only</span>
                  )}
                </div>
                {answer.graph.facts.length > 0 && (
                  <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-xs">
                    {answer.graph.facts.map((f, i) => (
                      <li key={i} className="flex flex-wrap items-center gap-1.5 px-3 py-2">
                        <span className="font-medium text-slate-900">{f.source}</span>
                        <Badge tone="brand">{f.relation}</Badge>
                        <span className="font-medium text-slate-900">{f.target}</span>
                        <span className="ml-auto text-slate-400">
                          {f.filename}
                          {f.page_number !== null ? `, p.${f.page_number}` : ""} · hop {f.hop}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </Card>

        <Card title="Build a graph from a document" description="Extract entities and relationships from one processed document.">
          <div className="space-y-4">
            <Alert tone="warning">
              This uses LLM calls (about one per {groupSize} chunks) and never runs automatically. Rebuilding replaces
              that document&apos;s previous graph.
            </Alert>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Max chunks">
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={maxChunks}
                  onChange={(e) => setMaxChunks(Number(e.target.value))}
                  className={inputClass}
                />
              </Field>
              <Field label="Chunks per call">
                <input
                  type="number"
                  min={1}
                  max={8}
                  value={groupSize}
                  onChange={(e) => setGroupSize(Number(e.target.value))}
                  className={inputClass}
                />
              </Field>
            </div>

            {documents.length === 0 ? (
              <EmptyState
                title="No processed documents"
                description="Upload a document to this workspace and wait for it to finish processing."
                action={
                  <ButtonLink href="/upload" size="sm">
                    Upload a document
                  </ButtonLink>
                }
              />
            ) : (
              <ul className="scrollbar-thin max-h-72 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
                {documents.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="font-mono text-xs text-slate-400">#{d.id}</span>
                      <span className="truncate text-slate-800" title={d.filename}>
                        {d.filename}
                      </span>
                    </span>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleBuild(d.id)}
                      disabled={buildingId !== null}
                      loading={buildingId === d.id}
                      className="shrink-0"
                    >
                      {buildingId === d.id ? "Building…" : `Build graph (≤ ${maxCalls} calls)`}
                    </Button>
                  </li>
                ))}
              </ul>
            )}

            {report && (
              <Alert tone="success" title={`Built from document #${report.document_id}`}>
                <p>
                  {report.entities} entities, {report.relationships} relationships from {report.chunks_processed}/
                  {report.chunks_total} chunks in {report.llm_calls} LLM call(s) (
                  {Math.round(report.elapsed_ms / 100) / 10}s)
                </p>
                <p>
                  Rejected for not matching the text: {report.dropped_entities} entities, {report.dropped_relations}{" "}
                  relationships
                  {report.groups_failed > 0 ? ` · ${report.groups_failed} call(s) failed and were skipped` : ""}
                  {report.truncated ? " · only the first chunks were processed" : ""}
                </p>
              </Alert>
            )}
          </div>
        </Card>
      </div>

      {graph && graph.nodes.length > 0 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <Card title="Entities" description={`${graph.nodes.length} shown, most connected first.`} padded={false}>
            <ul className="scrollbar-thin max-h-80 divide-y divide-slate-100 overflow-y-auto">
              {graph.nodes.map((node) => (
                <li key={node.id} className="flex items-center justify-between gap-2 px-5 py-2 text-sm">
                  <span className="flex min-w-0 items-center gap-2">
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: TYPE_COLORS[node.type] ?? TYPE_COLORS.OTHER }}
                    />
                    <span className="truncate text-slate-800" title={node.name}>
                      {node.name}
                    </span>
                  </span>
                  <span className="shrink-0 text-xs text-slate-400">
                    {node.type} · {node.degree}
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          <Card
            className="lg:col-span-2"
            title="Relationships"
            description={`${graph.edges.length} shown, each with the document it came from.`}
            padded={false}
          >
            {graph.edges.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-500">No relationships between the shown entities.</p>
            ) : (
              <ul className="scrollbar-thin max-h-80 divide-y divide-slate-100 overflow-y-auto">
                {graph.edges.map((edge) => (
                  <li key={edge.id} className="flex flex-wrap items-center gap-1.5 px-5 py-2 text-xs">
                    <span className="font-medium text-slate-900">{nodeNames.get(edge.source)}</span>
                    <Badge tone="brand">{edge.relation}</Badge>
                    <span className="font-medium text-slate-900">{nodeNames.get(edge.target)}</span>
                    <span className="ml-auto text-slate-400">
                      {edge.filename ?? "?"}
                      {edge.page_number !== null ? `, p.${edge.page_number}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

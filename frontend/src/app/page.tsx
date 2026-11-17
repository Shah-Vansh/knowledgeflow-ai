"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { DocumentSummary, listDocuments } from "@/lib/documents";
import { listConversations } from "@/lib/conversations";
import { useWorkspace } from "@/lib/workspace-context";
import { Alert, Badge, ButtonLink, Card, EmptyState, PageHeader, Stat, StatusBadge } from "@/components/ui";
import {
  AgentIcon,
  ArrowRightIcon,
  ChartIcon,
  ChatIcon,
  FlaskIcon,
  GraphIcon,
  SearchIcon,
  UploadIcon,
} from "@/components/icons";

const ACTIONS = [
  { href: "/chat", title: "Chat with your documents", text: "Ask follow-up questions; answers cite their sources.", icon: ChatIcon },
  { href: "/upload", title: "Add documents", text: "PDF, text, scans and images. Tables and OCR included.", icon: UploadIcon },
  { href: "/agent", title: "Ask the agent", text: "Routes to search, the graph, metadata or a calculator.", icon: AgentIcon },
  { href: "/graph", title: "Explore the knowledge graph", text: "Entities and relations, each backed by a passage.", icon: GraphIcon },
  { href: "/retrieval-lab", title: "Tune retrieval", text: "Dense, full-text, hybrid, reranking, query rewrites.", icon: FlaskIcon },
  { href: "/eval", title: "Measure quality", text: "Golden sets with recall, MRR and NDCG.", icon: ChartIcon },
];

const PIPELINE = [
  "Upload & extract (text, tables, OCR)",
  "Chunk & embed locally",
  "Hybrid search + RRF",
  "Cross-encoder rerank",
  "Grounded answer with sources",
];

export default function DashboardPage() {
  const { workspaceId, workspace } = useWorkspace();
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [conversationCount, setConversationCount] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    setDocuments(null);
    setConversationCount(null);
    setError("");
    listDocuments(undefined, workspaceId)
      .then((docs) => alive && setDocuments(docs))
      .catch((err) => alive && setError(err instanceof Error ? err.message : "Could not load documents"));
    listConversations(workspaceId)
      .then((list) => alive && setConversationCount(list.length))
      .catch(() => alive && setConversationCount(0));
    return () => {
      alive = false;
    };
  }, [workspaceId]);

  const processed = documents?.filter((d) => d.status === "processed").length ?? 0;
  const pending = documents?.filter((d) => d.status === "queued" || d.status === "processing").length ?? 0;
  const failed = documents?.filter((d) => d.status === "failed").length ?? 0;
  const recent = [...(documents ?? [])].sort((a, b) => b.id - a.id).slice(0, 5);
  const dash = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={workspace?.name ?? "Workspace"}
        title="Dashboard"
        description="Your knowledge base at a glance. Everything below is scoped to the workspace selected in the sidebar."
        actions={
          <>
            <ButtonLink href="/upload" variant="secondary">
              <UploadIcon className="h-4 w-4" /> Upload
            </ButtonLink>
            <ButtonLink href="/chat" variant="primary">
              <ChatIcon className="h-4 w-4" /> Start a chat
            </ButtonLink>
          </>
        }
      />

      {error && <Alert tone="error">{error}</Alert>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Documents" value={documents ? documents.length : "—"} hint={pending ? `${pending} in progress` : "in this workspace"} />
        <Stat label="Ready to search" value={documents ? processed : "—"} hint="processed documents" />
        <Stat label="Conversations" value={dash(conversationCount)} hint="saved chats" />
        <Stat label="Needs attention" value={documents ? failed : "—"} hint={failed ? "failed to process" : "nothing failed"} />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold text-slate-900">What would you like to do?</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {ACTIONS.map(({ href, title, text, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="group flex gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-card transition hover:border-brand-300 hover:shadow-md"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 group-hover:bg-brand-100">
                  <Icon className="h-5 w-5" />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1 text-sm font-medium text-slate-900">
                    {title}
                    <ArrowRightIcon className="h-3.5 w-3.5 -translate-x-1 opacity-0 transition group-hover:translate-x-0 group-hover:opacity-100" />
                  </span>
                  <span className="mt-0.5 block text-xs leading-5 text-slate-500">{text}</span>
                </span>
              </Link>
            ))}
          </div>
        </div>

        <Card title="How an answer is made" description="Every answer comes only from your documents.">
          <ol className="space-y-3">
            {PIPELINE.map((step, i) => (
              <li key={step} className="flex items-start gap-3 text-sm text-slate-700">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold text-brand-700">
                  {i + 1}
                </span>
                <span className="pt-0.5">{step}</span>
              </li>
            ))}
          </ol>
        </Card>
      </div>

      <Card
        title="Recent documents"
        actions={<ButtonLink href="/documents" variant="ghost" size="sm">View all</ButtonLink>}
        padded={recent.length === 0}
      >
        {documents && recent.length === 0 ? (
          <EmptyState
            icon={<SearchIcon className="h-8 w-8" />}
            title="No documents yet"
            description="Upload a PDF, text file or image to start asking questions about it."
            action={<ButtonLink href="/upload" variant="primary">Upload a document</ButtonLink>}
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {recent.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                <span className="min-w-0">
                  <span className="block truncate font-medium text-slate-900">{d.filename}</span>
                  <span className="text-xs text-slate-500">
                    {d.source_type ?? "file"}
                    {d.page_count ? ` · ${d.page_count} page${d.page_count === 1 ? "" : "s"}` : ""}
                    {d.uploaded_at ? ` · ${new Date(d.uploaded_at).toLocaleString()}` : ""}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {d.source_type && <Badge>{d.source_type}</Badge>}
                  <StatusBadge status={d.status} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

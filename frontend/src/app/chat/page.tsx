"use client";

import Markdown from "@/components/Markdown";
import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "@/lib/workspace-context";
import {
  ChatMessage,
  ConversationSummary,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  sendMessage,
} from "@/lib/conversations";
import { Alert, Badge, Button, ButtonLink, PageHeader, Spinner, cx, inputClass } from "@/components/ui";
import { ChatIcon, CloseIcon, DocumentsIcon } from "@/components/icons";

export default function ChatPage() {
  const { workspaceId, workspace } = useWorkspace();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const refreshConversations = (forWorkspace: number) =>
    listConversations(forWorkspace)
      .then(setConversations)
      .catch(() => setError("Could not load conversations"));

  useEffect(() => {
    setActiveId(null);
    setMessages([]);
    setError("");
    refreshConversations(workspaceId);
  }, [workspaceId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, sending]);

  const openConversation = async (id: number) => {
    setError("");
    try {
      const detail = await getConversation(id);
      setActiveId(id);
      setMessages(detail.messages);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open conversation");
    }
  };

  const startNewChat = () => {
    setActiveId(null);
    setMessages([]);
    setError("");
  };

  const removeConversation = async (id: number) => {
    setError("");
    try {
      await deleteConversation(id);
      if (activeId === id) startNewChat();
      refreshConversations(workspaceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete conversation");
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || sending) return;

    setSending(true);
    setError("");
    // Show the question at once (like any chat app) and clear the box; the server's
    // saved copy replaces this placeholder when the answer arrives.
    const pendingId = -Date.now();
    const pending: ChatMessage = {
      id: pendingId,
      role: "user",
      content: text,
      sources: [],
      standalone_question: null,
      created_at: null,
    };
    setMessages((prev) => [...prev, pending]);
    setInput("");
    try {
      let conversationId = activeId;
      if (conversationId === null) {
        const created = await createConversation(workspaceId);
        conversationId = created.id;
        setActiveId(created.id);
      }

      const result = await sendMessage(conversationId, text);
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== pendingId),
        result.user_message,
        result.assistant_message,
      ]);
      refreshConversations(workspaceId);
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== pendingId));
      setInput(text); // give the question back so it can be sent again
      setError(err instanceof Error ? err.message : "Could not send message");
    } finally {
      setSending(false);
    }
  };

  const activeTitle = conversations.find((c) => c.id === activeId)?.title;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Chat"
        description={
          <>
            Have a conversation with the documents in {workspace?.name ?? "this workspace"}. Follow-up
            questions like &ldquo;what is their main advantage?&rdquo; are understood using the conversation.
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:h-[calc(100vh-11rem)] lg:grid-cols-[260px_1fr]">
        {/* conversation list */}
        <aside className="flex min-h-0 flex-col rounded-xl border border-slate-200 bg-white shadow-card">
          <div className="border-b border-slate-100 p-3">
            <Button onClick={startNewChat} variant="secondary" className="w-full">
              + New chat
            </Button>
          </div>
          <div className="scrollbar-thin max-h-64 min-h-0 flex-1 overflow-y-auto p-2 lg:max-h-none">
            {conversations.length === 0 ? (
              <p className="px-2 py-6 text-center text-xs text-slate-500">
                No conversations in this workspace yet. Ask a question to start one.
              </p>
            ) : (
              <ul className="space-y-0.5">
                {conversations.map((c) => {
                  const active = c.id === activeId;
                  return (
                    <li
                      key={c.id}
                      className={cx(
                        "group flex items-center gap-1 rounded-lg text-sm transition-colors",
                        active ? "bg-brand-50 text-brand-700" : "text-slate-700 hover:bg-slate-100"
                      )}
                    >
                      <button
                        onClick={() => openConversation(c.id)}
                        className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2 text-left"
                        title={c.title}
                      >
                        <ChatIcon className={cx("h-4 w-4 shrink-0", active ? "text-brand-600" : "text-slate-400")} />
                        <span className="truncate">{c.title}</span>
                      </button>
                      <button
                        onClick={() => removeConversation(c.id)}
                        className="mr-1 rounded-md p-1 text-slate-400 hover:bg-red-50 hover:text-red-600"
                        aria-label={`Delete conversation ${c.title}`}
                        title="Delete conversation"
                      >
                        <CloseIcon className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        {/* thread */}
        <section className="flex h-[70vh] min-h-0 flex-col rounded-xl border border-slate-200 bg-slate-50/60 shadow-card lg:h-auto">
          <div className="flex items-center justify-between gap-3 rounded-t-xl border-b border-slate-200 bg-white px-5 py-3">
            <p className="truncate text-sm font-semibold text-slate-900">{activeTitle ?? "New conversation"}</p>
            {workspace && <Badge tone="brand">{workspace.name}</Badge>}
          </div>

          <div className="scrollbar-thin min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-5">
            {messages.length === 0 && !sending && (
              <div className="flex h-full flex-col items-center justify-center px-6 text-center">
                <ChatIcon className="mb-3 h-8 w-8 text-slate-300" />
                <p className="text-sm font-medium text-slate-900">Ask a question about this workspace</p>
                <p className="mt-1 max-w-sm text-sm text-slate-500">
                  Answers cite the documents they came from. No documents yet?
                </p>
                <div className="mt-4">
                  <ButtonLink href="/upload" size="sm">
                    <DocumentsIcon className="h-4 w-4" />
                    Upload documents
                  </ButtonLink>
                </div>
              </div>
            )}

            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-600 px-4 py-2.5 text-sm leading-6 text-white shadow-sm">
                    <p className="whitespace-pre-wrap">{m.content}</p>
                  </div>
                </div>
              ) : (
                <div key={m.id} className="flex justify-start">
                  <div className="max-w-[85%] space-y-3 rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 shadow-sm">
                    <Markdown text={m.content} />

                    {m.standalone_question && (
                      <p className="text-xs italic text-slate-400">Searched as: {m.standalone_question}</p>
                    )}

                    {m.sources.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 border-t border-slate-100 pt-2">
                        <span className="text-xs font-medium text-slate-500">Sources</span>
                        {m.sources.map((s) => (
                          <Badge key={`${s.document_id}-${s.page_number ?? "na"}`}>
                            {s.filename}
                            {s.page_number !== null ? ` · p.${s.page_number}` : ""}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )
            )}

            {sending && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl rounded-bl-md border border-slate-200 bg-white px-4 py-3 text-sm text-slate-500 shadow-sm">
                  <Spinner className="h-4 w-4" />
                  Thinking…
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {error && (
            <div className="px-4 pb-2">
              <Alert tone="error">{error}</Alert>
            </div>
          )}

          <div className="rounded-b-xl border-t border-slate-200 bg-white p-3">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSend();
                  }
                }}
                placeholder="Ask a question…"
                rows={2}
                maxLength={2000}
                className={cx(inputClass, "resize-none")}
              />
              <Button onClick={handleSend} disabled={!input.trim()} loading={sending} className="shrink-0">
                Send
              </Button>
            </div>
            <p className="mt-1.5 px-1 text-[11px] text-slate-400">Enter to send · Shift+Enter for a new line</p>
          </div>
        </section>
      </div>
    </div>
  );
}

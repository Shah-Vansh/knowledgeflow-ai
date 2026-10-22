"use client";

import { useEffect, useRef, useState } from "react";
import { listWorkspaces, Workspace } from "@/lib/workspaces";
import {
  ChatMessage,
  ConversationSummary,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  sendMessage,
} from "@/lib/conversations";

export default function ChatPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    listWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        if (list.length > 0) setWorkspaceId(list[0].id);
      })
      .catch(() => setError("Could not load workspaces"));
  }, []);

  const refreshConversations = (forWorkspace: number) =>
    listConversations(forWorkspace)
      .then(setConversations)
      .catch(() => setError("Could not load conversations"));

  useEffect(() => {
    if (workspaceId === null) return;
    setActiveId(null);
    setMessages([]);
    refreshConversations(workspaceId);
  }, [workspaceId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
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
      if (workspaceId !== null) refreshConversations(workspaceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete conversation");
    }
  };

  const handleSend = async () => {
    const text = input.trim();
    if (!text || workspaceId === null || sending) return;

    setSending(true);
    setError("");
    try {
      let conversationId = activeId;
      if (conversationId === null) {
        const created = await createConversation(workspaceId);
        conversationId = created.id;
        setActiveId(created.id);
      }

      const result = await sendMessage(conversationId, text);
      setMessages((prev) => [...prev, result.user_message, result.assistant_message]);
      setInput("");
      refreshConversations(workspaceId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send message");
    } finally {
      setSending(false);
    }
  };

  return (
    <main className="min-h-screen p-4 md:p-8 flex justify-center">
      <div className="w-full max-w-5xl grid grid-cols-1 md:grid-cols-[260px_1fr] gap-4">
        <aside className="border border-gray-300 rounded-lg bg-white p-3 space-y-3 h-fit">
          <label className="block text-sm">
            Workspace
            <select
              value={workspaceId ?? ""}
              onChange={(e) => setWorkspaceId(Number(e.target.value))}
              className="block w-full border border-gray-300 rounded p-1 mt-1"
            >
              {workspaces.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name} ({w.document_count})
                </option>
              ))}
            </select>
          </label>

          <button
            onClick={startNewChat}
            className="w-full border border-blue-600 text-blue-600 rounded-lg py-1.5 text-sm"
          >
            + New chat
          </button>

          <div className="space-y-1 max-h-80 overflow-y-auto">
            {conversations.length === 0 && (
              <p className="text-xs text-gray-500">No conversations in this workspace yet.</p>
            )}
            {conversations.map((c) => (
              <div
                key={c.id}
                className={`flex items-center justify-between gap-2 rounded px-2 py-1 text-sm ${
                  c.id === activeId ? "bg-blue-50 border border-blue-200" : "hover:bg-gray-50"
                }`}
              >
                <button
                  onClick={() => openConversation(c.id)}
                  className="text-left truncate flex-1"
                  title={c.title}
                >
                  {c.title}
                </button>
                <button
                  onClick={() => removeConversation(c.id)}
                  className="text-xs text-red-600"
                  aria-label={`Delete conversation ${c.title}`}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>

          <div className="text-xs text-gray-500 flex justify-between pt-1">
            <a href="/workspaces" className="text-blue-600 underline">
              Workspaces
            </a>
            <a href="/upload" className="text-blue-600 underline">
              Upload
            </a>
          </div>
        </aside>

        <section className="border border-gray-300 rounded-lg bg-white flex flex-col min-h-[70vh]">
          <div className="flex-1 p-4 space-y-4 overflow-y-auto">
            {messages.length === 0 && (
              <p className="text-sm text-gray-500">
                Ask a question about the documents in this workspace. Follow-up questions like
                &ldquo;what is their main advantage?&rdquo; are understood using the conversation.
              </p>
            )}

            {messages.map((m) => (
              <div key={m.id} className={m.role === "user" ? "flex justify-end" : "flex justify-start"}>
                <div
                  className={`max-w-[85%] rounded-lg p-3 text-sm space-y-2 ${
                    m.role === "user" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-900"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{m.content}</p>

                  {m.role === "assistant" && m.standalone_question && (
                    <p className="text-xs italic text-gray-500">
                      Searched as: {m.standalone_question}
                    </p>
                  )}

                  {m.role === "assistant" && m.sources.length > 0 && (
                    <div className="text-xs text-gray-600">
                      <p className="font-medium">Sources</p>
                      <ul className="list-disc list-inside">
                        {m.sources.map((s) => (
                          <li key={`${s.document_id}-${s.page_number ?? "na"}`}>
                            {s.filename}
                            {s.page_number !== null ? ` — page ${s.page_number}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {sending && <p className="text-sm text-gray-500">Thinking...</p>}
            <div ref={bottomRef} />
          </div>

          {error && <div className="px-4 pb-2 text-sm text-red-600">{error}</div>}

          <div className="border-t border-gray-200 p-3 flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Ask a question... (Enter to send, Shift+Enter for a new line)"
              rows={2}
              maxLength={2000}
              className="flex-1 border border-gray-300 rounded-lg p-2 text-sm"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending || workspaceId === null}
              className="bg-blue-600 text-white rounded-lg px-4 text-sm disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </section>
      </div>
    </main>
  );
}
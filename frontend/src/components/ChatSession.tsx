import { useState, useEffect, useRef } from "react";
import { getSession, sendFollowUp } from "../api";
import type { ChatSessionDetail, SessionMessage, Source } from "../types";
import AnswerPanel from "./AnswerPanel";
import SourceFooter from "./SourceFooter";
import CitationPanel from "./CitationPanel";
import ContextBar from "./ContextBar";

interface PanelState {
  sources:    Source[];
  focusIndex: number | null;
}

interface Props {
  sessionId:    number;
  contextLimit: number;
  model:        string;
  onBack:       () => void;
}

interface StreamingTurn {
  text:    string;
  sources: Source[];
}

export default function ChatSession({ sessionId, contextLimit, model, onBack }: Props) {
  const [session,      setSession]      = useState<ChatSessionDetail | null>(null);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState<string | null>(null);

  const [input,        setInput]        = useState("");
  const [streaming,    setStreaming]     = useState(false);
  const [streamTurn,   setStreamTurn]   = useState<StreamingTurn | null>(null);

  const [tokensUsed,   setTokensUsed]   = useState(0);
  const [panel,        setPanel]        = useState<PanelState | null>(null);

  const bottomRef  = useRef<HTMLDivElement>(null);
  const abortRef   = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function load() {
    try {
      const s = await getSession(sessionId);
      setSession(s);
      setTokensUsed(s.tokens_used);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load session");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [sessionId]);

  // Auto-scroll on new content
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length, streamTurn?.text]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  const isExhausted = tokensUsed >= contextLimit;

  async function handleSend() {
    if (!input.trim() || streaming || isExhausted) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const question = input.trim();
    setInput("");
    setStreaming(true);
    setError(null);
    setStreamTurn({ text: "", sources: [] });
    setPanel(null);

    try {
      await sendFollowUp(sessionId, question, {
        onSources:    (s) => setStreamTurn((prev) => prev ? { ...prev, sources: s } : null),
        onChunk:      (t) => setStreamTurn((prev) => prev ? { ...prev, text: prev.text + t } : null),
        onCitations:  () => {},
        onTokenCount: (used) => setTokensUsed(used),
        onDone:       async () => {
          setStreaming(false);
          setStreamTurn(null);
          await load();  // refresh with saved messages
        },
        onError: (d) => {
          setStreaming(false);
          setStreamTurn(null);
          setError(d);
        },
      }, controller.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "Something went wrong");
      }
      setStreaming(false);
      setStreamTurn(null);
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSend();
    }
  }

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-10 flex flex-col gap-3 animate-pulse">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-12 rounded-xl bg-gray-100 dark:bg-slate-800" />
        ))}
      </div>
    );
  }

  // Pair messages into turns: user[i] + assistant[i+1]
  const messages = session?.messages ?? [];

  function handleCitationClick(index: number, msgSources: Source[]) {
    setPanel((prev) =>
      prev?.focusIndex === index && prev.sources === msgSources
        ? null
        : { sources: msgSources, focusIndex: index }
    );
  }

  function handleFooterChipClick(rep: Source, fileChunks: Source[]) {
    setPanel({ sources: fileChunks, focusIndex: null });
  }

  return (
    <div className="max-w-3xl mx-auto px-4 flex flex-col" style={{ minHeight: "calc(100vh - 57px)" }}>
      {panel && (
        <CitationPanel
          sources={panel.sources}
          focusIndex={panel.focusIndex}
          onClose={() => setPanel(null)}
        />
      )}

      {/* Top bar: back link + context bar */}
      <div className="sticky top-[57px] z-10 bg-white/90 dark:bg-slate-950/80
                      backdrop-blur border-b border-gray-100 dark:border-slate-800 py-2.5">
        <div className="flex items-center gap-4">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-slate-500
                       hover:text-gray-700 dark:hover:text-slate-200 transition-colors flex-shrink-0"
          >
            <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5"
                 stroke="currentColor" strokeWidth="1.5">
              <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            New chat
          </button>
          <div className="flex-1">
            <ContextBar tokensUsed={tokensUsed} contextLimit={contextLimit} />
          </div>
        </div>
      </div>

      {/* Message thread */}
      <div className="flex-1 py-6 flex flex-col gap-8">
        {messages.map((msg, i) => (
          <MessageBubble
            key={msg.id}
            msg={msg}
            model={model}
            onCitationClick={(idx) => handleCitationClick(idx, msg.sources)}
            onChipClick={(rep, chunks) => handleFooterChipClick(rep, chunks)}
          />
        ))}

        {/* Streaming turn */}
        {streamTurn && (
          <div className="flex flex-col gap-6">
            {/* Pending user bubble */}
            <div className="flex justify-end">
              <div className="max-w-[80%] px-4 py-2.5 rounded-2xl rounded-br-sm text-sm
                              bg-pink-500 text-white">
                {input || (session?.messages[session.messages.length - 1]?.content ?? "…")}
              </div>
            </div>
            {/* Streaming answer */}
            <div className="flex flex-col gap-6">
              {streamTurn.text && (
                <>
                  <div className="border-t border-gray-100 dark:border-slate-800" />
                  <AnswerPanel
                    text={streamTurn.text}
                    model={model}
                    chunkCount={streamTurn.sources.length}
                    onCitationClick={() => {}}
                    pending={true}
                  />
                  {streamTurn.sources.length > 0 && (
                    <SourceFooter
                      sources={streamTurn.sources}
                      onChipClick={handleFooterChipClick}
                    />
                  )}
                </>
              )}
              {!streamTurn.text && (
                <div className="flex flex-col gap-2 animate-pulse">
                  <div className="h-3 bg-gray-100 dark:bg-slate-800 rounded w-16" />
                  <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-full" />
                  <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-5/6" />
                  <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-4/6" />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="flex items-start gap-3 rounded-lg px-4 py-3 text-sm
                          bg-red-50 border border-red-200 text-red-600
                          dark:bg-red-950/50 dark:border-red-800 dark:text-red-400">
            <span className="mt-0.5">⚠</span>
            <span>{error}</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="sticky bottom-0 pb-4 pt-2
                      bg-white/90 dark:bg-slate-950/80 backdrop-blur">
        <div className={`relative flex items-end gap-3 p-3 rounded-xl shadow-sm transition-all
                        bg-white dark:bg-slate-900
                        border ${isExhausted
                          ? "border-red-300 dark:border-red-700"
                          : "border-gray-200 dark:border-slate-700 focus-within:border-pink-400 dark:focus-within:border-pink-500 focus-within:ring-1 focus-within:ring-pink-400"
                        }`}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKey}
            disabled={streaming || isExhausted}
            placeholder={isExhausted ? "Context limit reached — start a new chat" : "Ask a follow-up question… (⌘↵ to send)"}
            rows={1}
            className="flex-1 resize-none bg-transparent text-base leading-relaxed
                       focus:outline-none disabled:opacity-50 min-h-[40px] max-h-48 overflow-y-auto
                       text-gray-900 dark:text-slate-100
                       placeholder-gray-300 dark:placeholder-slate-600"
          />
          <button
            onClick={handleSend}
            disabled={streaming || isExhausted || !input.trim()}
            className="flex-shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg
                       text-sm font-medium transition-all shadow-sm
                       bg-gradient-to-r from-pink-500 to-purple-500
                       hover:from-pink-600 hover:to-purple-600
                       text-white
                       disabled:from-gray-200 disabled:to-gray-200 disabled:text-gray-400
                       dark:disabled:from-slate-700 dark:disabled:to-slate-700 dark:disabled:text-slate-500"
          >
            {streaming ? (
              <span className="flex items-center gap-2">
                <Spinner /> Thinking…
              </span>
            ) : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Per-message bubble ─────────────────────────────────────────────────────────

function MessageBubble({
  msg, model, onCitationClick, onChipClick,
}: {
  msg:             SessionMessage;
  model:           string;
  onCitationClick: (i: number) => void;
  onChipClick:     (rep: Source, chunks: Source[]) => void;
}) {
  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] px-4 py-2.5 rounded-2xl rounded-br-sm text-sm
                        bg-pink-500 text-white leading-relaxed">
          {msg.content}
        </div>
      </div>
    );
  }

  // Assistant
  return (
    <div className="flex flex-col gap-4">
      <AnswerPanel
        text={msg.content}
        model={model}
        chunkCount={msg.sources.length}
        onCitationClick={onCitationClick}
        pending={false}
      />
      {msg.sources.length > 0 && (
        <SourceFooter sources={msg.sources} onChipClick={onChipClick} />
      )}
    </div>
  );
}

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

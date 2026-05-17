import { useState, useEffect } from "react";
import { getHistory, getConversation, deleteConversation } from "../api";
import type { ConversationSummary, ConversationDetail } from "../types";
import AnswerPanel from "../components/AnswerPanel";
import SourceList from "../components/SourceList";

const PAGE_SIZE = 20;

interface Props {
  activeChatId:       number | null;
  onClearActiveChatId: () => void;
}

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins  = Math.floor(diff / 60_000);
  const hours = Math.floor(diff / 3_600_000);
  const days  = Math.floor(diff / 86_400_000);
  if (mins  < 1)   return "just now";
  if (mins  < 60)  return `${mins}m ago`;
  if (hours < 24)  return `${hours}h ago`;
  if (days  < 30)  return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function HistoryPage({ activeChatId, onClearActiveChatId }: Props) {
  const [items,   setItems]   = useState<ConversationSummary[]>([]);
  const [total,   setTotal]   = useState(0);
  const [offset,  setOffset]  = useState(0);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  // Expanded conversation detail
  const [expandedId,   setExpandedId]   = useState<number | null>(null);
  const [detail,       setDetail]       = useState<ConversationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeIndex,  setActiveIndex]  = useState<number | null>(null);

  async function load(newOffset = 0) {
    setLoading(true);
    setError(null);
    try {
      const data = await getHistory(PAGE_SIZE, newOffset);
      setItems(data.items);
      setTotal(data.total);
      setOffset(newOffset);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load history");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(0); }, []);

  // Auto-expand a conversation linked from the sidebar
  useEffect(() => {
    if (activeChatId != null) {
      handleExpand(activeChatId);
      onClearActiveChatId();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeChatId]);

  async function handleExpand(id: number) {
    if (expandedId === id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(id);
    setDetail(null);
    setActiveIndex(null);
    setDetailLoading(true);
    try {
      const d = await getConversation(id);
      setDetail(d);
    } catch {
      setExpandedId(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleDelete(e: React.MouseEvent, id: number) {
    e.stopPropagation();
    if (!confirm("Delete this conversation?")) return;
    try {
      await deleteConversation(id);
      if (expandedId === id) { setExpandedId(null); setDetail(null); }
      await load(offset);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <main className="max-w-3xl mx-auto px-4 py-10">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-slate-100">
          Chat history
        </h1>
        <p className="text-sm text-gray-400 dark:text-slate-500 mt-0.5">
          {total === 0 ? "No conversations yet" : `${total} conversation${total !== 1 ? "s" : ""}`}
        </p>
      </div>

      {/* Error banner */}
      {error && (
        <div className="mb-4 px-3 py-2 rounded-lg text-sm bg-red-50 border border-red-200
                        text-red-600 dark:bg-red-950/50 dark:border-red-800 dark:text-red-400">
          {error}
        </div>
      )}

      {/* List */}
      {loading ? (
        <div className="flex flex-col gap-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-14 rounded-xl bg-gray-100 dark:bg-slate-800 animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-20 text-center">
          <div className="w-12 h-12 rounded-full bg-gray-100 dark:bg-slate-800
                          flex items-center justify-center">
            <svg viewBox="0 0 20 20" fill="none" className="w-5 h-5 text-gray-400 dark:text-slate-500"
                 stroke="currentColor" strokeWidth="1.5">
              <path d="M2 4.5A1.5 1.5 0 013.5 3h13A1.5 1.5 0 0118 4.5v9a1.5 1.5 0 01-1.5 1.5H11l-3 3v-3H3.5A1.5 1.5 0 012 13.5v-9z"
                    strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p className="text-sm text-gray-400 dark:text-slate-500">
            Ask a question to start building your history
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <div key={item.id}
                 className="rounded-xl border border-gray-200 dark:border-slate-700 overflow-hidden">
              {/* Row header — always visible */}
              <button
                onClick={() => handleExpand(item.id)}
                className="w-full flex items-center gap-3 px-4 py-3
                           bg-white dark:bg-slate-950
                           hover:bg-gray-50 dark:hover:bg-slate-900
                           transition-colors text-left"
              >
                {/* Chevron */}
                <svg viewBox="0 0 16 16" fill="none"
                     className={`w-3.5 h-3.5 flex-shrink-0 text-gray-400 dark:text-slate-500
                                 transition-transform duration-150
                                 ${expandedId === item.id ? "rotate-90" : ""}`}
                     stroke="currentColor" strokeWidth="1.5">
                  <path d="M6 3l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>

                {/* Title */}
                <span className="flex-1 text-sm font-medium text-gray-800 dark:text-slate-200 truncate">
                  {item.title}
                </span>

                {/* Meta */}
                <span className="flex-shrink-0 text-xs text-gray-400 dark:text-slate-500 mr-2">
                  {item.model}
                </span>
                <span className="flex-shrink-0 text-xs text-gray-400 dark:text-slate-500 mr-2">
                  {relativeTime(item.created_at)}
                </span>

                {/* Delete */}
                <button
                  onClick={(e) => handleDelete(e, item.id)}
                  title="Delete"
                  className="flex-shrink-0 p-1 rounded-md
                             text-gray-300 dark:text-slate-600
                             hover:text-red-500 dark:hover:text-red-400
                             hover:bg-red-50 dark:hover:bg-red-950/30
                             transition-colors"
                >
                  <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5"
                       stroke="currentColor" strokeWidth="1.5">
                    <path d="M3 4h10M6 4V2.5a.5.5 0 01.5-.5h3a.5.5 0 01.5.5V4M5 4l.5 9h5L11 4"
                          strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </button>

              {/* Expanded detail */}
              {expandedId === item.id && (
                <div className="border-t border-gray-100 dark:border-slate-800
                                bg-gray-50 dark:bg-slate-900 px-5 py-5 flex flex-col gap-6">
                  {/* Question */}
                  <div className="px-4 py-3 rounded-lg bg-white dark:bg-slate-950
                                  border border-gray-200 dark:border-slate-700">
                    <p className="text-xs font-semibold uppercase tracking-widest
                                  text-gray-400 dark:text-slate-500 mb-1">
                      Question
                    </p>
                    <p className="text-sm text-gray-800 dark:text-slate-200">
                      {detail?.question ?? item.title}
                    </p>
                  </div>

                  {detailLoading ? (
                    <div className="flex flex-col gap-2 animate-pulse">
                      <div className="h-3 bg-gray-200 dark:bg-slate-700 rounded w-12" />
                      <div className="h-4 bg-gray-200 dark:bg-slate-700 rounded w-full" />
                      <div className="h-4 bg-gray-200 dark:bg-slate-700 rounded w-5/6" />
                      <div className="h-4 bg-gray-200 dark:bg-slate-700 rounded w-4/6" />
                    </div>
                  ) : detail ? (
                    <>
                      <AnswerPanel
                        text={detail.answer}
                        model={detail.model}
                        chunkCount={detail.sources.length}
                        onCitationClick={(i) =>
                          setActiveIndex((prev) => (prev === i ? null : i))
                        }
                        pending={false}
                      />
                      {detail.sources.length > 0 && (
                        <>
                          <div className="border-t border-gray-200 dark:border-slate-700" />
                          <SourceList sources={detail.sources} activeIndex={activeIndex} />
                        </>
                      )}
                    </>
                  ) : null}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 mt-6">
          <button
            onClick={() => load(offset - PAGE_SIZE)}
            disabled={currentPage <= 1}
            className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-slate-700
                       text-gray-600 dark:text-slate-400
                       hover:bg-gray-100 dark:hover:bg-slate-800
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            ← Previous
          </button>
          <span className="text-sm text-gray-400 dark:text-slate-500">
            {currentPage} / {totalPages}
          </span>
          <button
            onClick={() => load(offset + PAGE_SIZE)}
            disabled={currentPage >= totalPages}
            className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-slate-700
                       text-gray-600 dark:text-slate-400
                       hover:bg-gray-100 dark:hover:bg-slate-800
                       disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </main>
  );
}

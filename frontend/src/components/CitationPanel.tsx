import { useEffect, useRef, useState } from "react";
import type { Source } from "../types";
import { getDocument } from "../api";
import type { DocumentResponse } from "../api";
import TickerBadge from "./TickerBadge";

interface Props {
  sources:    Source[];
  focusIndex: number | null;
  onClose:    () => void;
}

type View = "chunks" | "document";

// ── Highlight helpers ──────────────────────────────────────────────────────────

interface Range {
  start:      number;
  end:        number;
  chunkIndex: number;
}

function buildHighlightRanges(text: string, sources: Source[]): Range[] {
  const ranges: Range[] = [];
  for (const s of sources) {
    // Use first 200 chars of snippet for a reliable match (avoids truncation edge cases)
    const needle = s.snippet.slice(0, 200).trim();
    if (!needle) continue;
    const pos = text.indexOf(needle);
    if (pos === -1) continue;
    ranges.push({ start: pos, end: pos + s.snippet.length, chunkIndex: s.index });
  }
  // Sort by position and remove overlaps (keep first)
  ranges.sort((a, b) => a.start - b.start);
  const merged: Range[] = [];
  for (const r of ranges) {
    if (merged.length && r.start < merged[merged.length - 1].end) continue;
    merged.push(r);
  }
  return merged;
}

interface Segment {
  text:       string;
  highlight:  boolean;
  chunkIndex: number | null;
}

function buildSegments(text: string, ranges: Range[]): Segment[] {
  const segs: Segment[] = [];
  let cursor = 0;
  for (const r of ranges) {
    if (cursor < r.start) {
      segs.push({ text: text.slice(cursor, r.start), highlight: false, chunkIndex: null });
    }
    segs.push({ text: text.slice(r.start, r.end), highlight: true, chunkIndex: r.chunkIndex });
    cursor = r.end;
  }
  if (cursor < text.length) {
    segs.push({ text: text.slice(cursor), highlight: false, chunkIndex: null });
  }
  return segs;
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function CitationPanel({ sources, focusIndex, onClose }: Props) {
  const panelRef   = useRef<HTMLDivElement>(null);
  const docBodyRef = useRef<HTMLDivElement>(null);

  const [view,       setView]       = useState<View>("chunks");
  const [doc,        setDoc]        = useState<DocumentResponse | null>(null);
  const [docLoading, setDocLoading] = useState(false);
  const [docError,   setDocError]   = useState<string | null>(null);

  // Reset to chunk view when sources change (new panel opened)
  useEffect(() => {
    setView("chunks");
    setDoc(null);
    setDocError(null);
  }, [sources]);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Scroll focused chunk into view (chunks view)
  useEffect(() => {
    if (view !== "chunks" || focusIndex == null) return;
    const el = panelRef.current?.querySelector(`[data-index="${focusIndex}"]`);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [focusIndex, sources, view]);

  // Scroll to first highlight when document loads
  useEffect(() => {
    if (view !== "document" || !doc) return;
    const el = docBodyRef.current?.querySelector("[data-highlight]");
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [view, doc]);

  const firstSource = sources[0];

  async function handleToggleView() {
    if (view === "document") {
      setView("chunks");
      return;
    }
    // Switch to document view — fetch if not yet loaded
    if (doc) { setView("document"); return; }
    if (!firstSource) return;
    setDocLoading(true);
    setDocError(null);
    try {
      const data = await getDocument(
        firstSource.ticker,
        firstSource.filing_type,
        firstSource.filing_date,
        firstSource.section,
      );
      setDoc(data);
      setView("document");
    } catch (e) {
      setDocError(e instanceof Error ? e.message : "Failed to load document");
    } finally {
      setDocLoading(false);
    }
  }

  // Pre-compute highlight segments when in document view
  const segments: Segment[] = view === "document" && doc
    ? buildSegments(doc.text, buildHighlightRanges(doc.text, sources))
    : [];

  return (
    <>
      {/* Backdrop — mobile only */}
      <div
        className="fixed inset-0 z-40 bg-black/20 dark:bg-black/40 lg:hidden"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        className="fixed top-0 right-0 z-50 h-full w-full max-w-sm
                   bg-white dark:bg-slate-900
                   border-l border-gray-200 dark:border-slate-700
                   shadow-2xl flex flex-col
                   animate-slide-in-right"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-2 px-4 py-3
                        border-b border-gray-100 dark:border-slate-800 flex-shrink-0">
          <div className="flex flex-col gap-0.5 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {firstSource && <TickerBadge ticker={firstSource.ticker} />}
              <span className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate">
                {firstSource
                  ? `${firstSource.filing_type.split(" ")[0]} · ${firstSource.filing_date}`
                  : "Sources"}
              </span>
            </div>
            {firstSource?.section && (
              <span className="text-xs font-mono text-gray-400 dark:text-slate-500">
                {view === "document" ? "Full document" : firstSource.section}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5 flex-shrink-0">
            {/* Show document / Back to chunks toggle */}
            {firstSource && (
              <button
                onClick={handleToggleView}
                disabled={docLoading}
                className="flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium
                           border border-gray-200 dark:border-slate-700
                           text-gray-600 dark:text-slate-400
                           hover:border-pink-300 dark:hover:border-pink-700
                           hover:text-pink-600 dark:hover:text-pink-400
                           hover:bg-pink-50 dark:hover:bg-pink-950/30
                           disabled:opacity-50 disabled:cursor-not-allowed
                           transition-colors"
              >
                {docLoading ? (
                  <Spinner />
                ) : view === "document" ? (
                  <>
                    <svg viewBox="0 0 16 16" fill="none" className="w-3 h-3"
                         stroke="currentColor" strokeWidth="1.5">
                      <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Chunks
                  </>
                ) : (
                  <>
                    <svg viewBox="0 0 16 16" fill="none" className="w-3 h-3"
                         stroke="currentColor" strokeWidth="1.5">
                      <path d="M2 4h12M2 8h8M2 12h10" strokeLinecap="round" />
                    </svg>
                    Show document
                  </>
                )}
              </button>
            )}

            {/* Close */}
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-gray-400 dark:text-slate-500
                         hover:text-gray-700 dark:hover:text-slate-200
                         hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
            >
              <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4"
                   stroke="currentColor" strokeWidth="1.5">
                <path d="M3 3l10 10M13 3L3 13" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body */}
        {view === "chunks" ? (
          /* ── Chunk list ── */
          <div className="flex-1 overflow-y-auto px-4 py-3 flex flex-col gap-4">
            {sources.map((s) => (
              <div
                key={s.index}
                data-index={s.index}
                className={`rounded-xl border p-3 transition-all duration-200
                            ${focusIndex === s.index
                              ? "border-pink-400 dark:border-pink-600 bg-pink-50/50 dark:bg-pink-950/20 ring-1 ring-pink-300 dark:ring-pink-700"
                              : "border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-950"
                            }`}
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="w-5 h-5 rounded text-xs font-semibold flex items-center justify-center
                                   bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 flex-shrink-0">
                    {s.index}
                  </span>
                  <span className="text-xs font-mono text-gray-400 dark:text-slate-500 truncate">
                    {s.section}
                  </span>
                </div>
                <p className="text-sm leading-relaxed text-gray-700 dark:text-slate-300
                               whitespace-pre-wrap font-mono">
                  {s.snippet}
                  {s.snippet.length >= 400 && (
                    <span className="text-gray-400 dark:text-slate-600"> …</span>
                  )}
                </p>
              </div>
            ))}
          </div>
        ) : docError ? (
          /* ── Error ── */
          <div className="flex-1 flex items-center justify-center px-6">
            <div className="text-center flex flex-col gap-2">
              <p className="text-sm text-red-600 dark:text-red-400">{docError}</p>
              <button
                onClick={() => { setView("chunks"); setDocError(null); }}
                className="text-xs text-gray-400 dark:text-slate-500 underline"
              >
                Back to chunks
              </button>
            </div>
          </div>
        ) : (
          /* ── Document view ── */
          <div
            ref={docBodyRef}
            className="flex-1 overflow-y-auto px-4 py-4"
          >
            {/* Highlight count badge */}
            {segments.filter((s) => s.highlight).length > 0 && (
              <p className="text-[11px] text-gray-400 dark:text-slate-500 mb-3">
                {segments.filter((s) => s.highlight).length} retrieved chunk
                {segments.filter((s) => s.highlight).length !== 1 ? "s" : ""} highlighted
              </p>
            )}

            <p className="text-sm leading-relaxed text-gray-700 dark:text-slate-300
                           whitespace-pre-wrap font-mono">
              {segments.map((seg, i) =>
                seg.highlight ? (
                  <mark
                    key={i}
                    data-highlight
                    className="relative inline bg-pink-100 dark:bg-pink-950/40
                               border-l-2 border-pink-400 dark:border-pink-600
                               text-gray-800 dark:text-slate-200
                               rounded-sm px-0.5 not-italic"
                  >
                    <span className="absolute -top-4 left-0
                                     inline-flex items-center justify-center
                                     w-4 h-4 rounded text-[10px] font-bold
                                     bg-pink-500 text-white leading-none">
                      {seg.chunkIndex}
                    </span>
                    {seg.text}
                  </mark>
                ) : (
                  <span key={i}>{seg.text}</span>
                )
              )}
            </p>
          </div>
        )}
      </div>
    </>
  );
}

function Spinner() {
  return (
    <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10"
              stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor"
            d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

import { useState } from "react";
import { askQuestion } from "./api";
import type { AskResponse } from "./types";
import QueryBox from "./components/QueryBox";
import AnswerPanel from "./components/AnswerPanel";
import SourceList from "./components/SourceList";
import ModelPicker from "./components/ModelPicker";

export default function App() {
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState("gpt-5.4-mini");
  const [result, setResult] = useState<AskResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);

  async function handleSubmit() {
    if (!question.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setActiveIndex(null);

    try {
      const res = await askQuestion({ question, model, top_k: 15 });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  function handleCitationClick(index: number) {
    setActiveIndex((prev) => (prev === index ? null : index));
  }

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-950/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded bg-blue-600 flex items-center justify-center">
              <svg viewBox="0 0 16 16" fill="white" className="w-3.5 h-3.5">
                <path d="M2 2h5v5H2V2zm7 0h5v5H9V2zm-7 7h5v5H2V9zm7 0h5v5H9V9z" />
              </svg>
            </div>
            <span className="font-semibold text-slate-100 tracking-tight">SEC EDGAR Research</span>
            <span className="text-xs text-slate-600 hidden sm:inline">54 companies · 2021–2026</span>
          </div>
          <ModelPicker value={model} onChange={setModel} disabled={loading} />
        </div>
      </header>

      {/* Main */}
      <main className="max-w-3xl mx-auto px-4 py-8 flex flex-col gap-8">

        {/* Query box */}
        <QueryBox
          value={question}
          onChange={setQuestion}
          onSubmit={handleSubmit}
          loading={loading}
        />

        {/* Error */}
        {error && (
          <div className="flex items-start gap-3 bg-red-950/50 border border-red-800 text-red-300 rounded-lg px-4 py-3 text-sm">
            <span className="mt-0.5">⚠</span>
            <span>{error}</span>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && (
          <div className="flex flex-col gap-4 animate-pulse">
            <div className="h-3 bg-slate-800 rounded w-16" />
            <div className="flex flex-col gap-2">
              <div className="h-4 bg-slate-800 rounded w-full" />
              <div className="h-4 bg-slate-800 rounded w-5/6" />
              <div className="h-4 bg-slate-800 rounded w-4/6" />
              <div className="h-4 bg-slate-800 rounded w-full" />
              <div className="h-4 bg-slate-800 rounded w-3/4" />
            </div>
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <>
            <div className="border-t border-slate-800" />
            <AnswerPanel
              text={result.answer}
              model={model}
              chunkCount={result.sources.length}
              activeIndex={activeIndex}
              onCitationClick={handleCitationClick}
            />
            <div className="border-t border-slate-800" />
            <SourceList sources={result.sources} activeIndex={activeIndex} />
          </>
        )}

        {/* Empty state */}
        {!result && !loading && !error && (
          <div className="text-center py-16 text-slate-700">
            <svg viewBox="0 0 48 48" fill="none" className="w-12 h-12 mx-auto mb-4 opacity-40">
              <rect x="6" y="6" width="36" height="36" rx="4" stroke="currentColor" strokeWidth="2" />
              <path d="M14 18h20M14 24h14M14 30h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <p className="text-sm">Ask a question to search across 246 SEC filings</p>
          </div>
        )}
      </main>
    </div>
  );
}

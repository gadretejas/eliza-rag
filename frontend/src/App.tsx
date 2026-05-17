import { useState, useRef } from "react";
import { streamQuestion } from "./api";
import type { Source, SavedModel } from "./types";
import { useTheme } from "./useTheme";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import QueryBox from "./components/QueryBox";
import AnswerPanel from "./components/AnswerPanel";
import SourceList from "./components/SourceList";
import ModelPicker from "./components/ModelPicker";
import ThemeToggle from "./components/ThemeToggle";
import Sidebar from "./components/Sidebar";
import SettingsPage from "./components/SettingsPage";
import AboutDataPage from "./components/AboutDataPage";
import AdminPage from "./pages/AdminPage";

type Page = "chat" | "about" | "settings" | "admin";

function loadSavedModels(): SavedModel[] {
  try {
    const raw = localStorage.getItem("savedModels");
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function persistModels(models: SavedModel[]) {
  localStorage.setItem("savedModels", JSON.stringify(models));
}

function AppInner() {
  const { theme, toggle }             = useTheme();
  const { user }                      = useAuth();
  const [page, setPage]               = useState<Page>("chat");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [savedModels, setSavedModels]       = useState<SavedModel[]>(loadSavedModels);
  const [question, setQuestion]             = useState("");
  const [model, setModel]                   = useState("gpt-5.4-mini");
  const [streamingText, setStreamingText]   = useState("");
  const [sources, setSources]               = useState<Source[]>([]);
  const [validCitations, setValidCitations] = useState<number[]>([]);
  const [streaming, setStreaming]           = useState(false);
  const [done, setDone]                     = useState(false);
  const [error, setError]                   = useState<string | null>(null);
  const [activeIndex, setActiveIndex]       = useState<number | null>(null);
  const abortRef                            = useRef<AbortController | null>(null);

  function handleAddModel(m: SavedModel) {
    const updated = [...savedModels, m];
    setSavedModels(updated);
    persistModels(updated);
  }

  function handleDeleteModel(id: string) {
    const updated = savedModels.filter((m) => m.id !== id);
    setSavedModels(updated);
    persistModels(updated);
    if (model === id) setModel("gpt-5.4-mini");
  }

  async function handleSubmit() {
    if (!question.trim() || streaming) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStreaming(true);
    setDone(false);
    setError(null);
    setStreamingText("");
    setSources([]);
    setValidCitations([]);
    setActiveIndex(null);

    const custom = savedModels.find((m) => m.id === model);
    const req = custom
      ? {
          question,
          model:    custom.modelName,
          top_k:    15,
          provider: custom.provider,
          api_key:  custom.apiKey || undefined,
          base_url: custom.baseUrl || undefined,
        }
      : { question, model, top_k: 15 };

    try {
      await streamQuestion(req, {
        onSources:   (s) => setSources(s),
        onChunk:     (t) => setStreamingText((prev) => prev + t),
        onCitations: (v) => setValidCitations(v),
        onDone:      ()  => { setStreaming(false); setDone(true); },
        onError:     (d) => { setStreaming(false); setError(d); },
      }, controller.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "Something went wrong");
      }
      setStreaming(false);
    }
  }

  function handleCitationClick(index: number) {
    setActiveIndex((prev) => (prev === index ? null : index));
  }

  return (
    <div className="min-h-screen bg-white dark:bg-slate-950">
      <Sidebar
        open={sidebarOpen}
        currentPage={page}
        onNavigate={setPage}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Header */}
      <header className="border-b border-gray-100 dark:border-slate-800
                         bg-white/90 dark:bg-slate-950/80 backdrop-blur sticky top-0 z-30 shadow-sm">
        <div className="flex items-center px-3 py-3 gap-3">
          <button
            onClick={() => setSidebarOpen(true)}
            title="Menu"
            className="flex-shrink-0 p-1.5 rounded-lg text-gray-400 dark:text-slate-500
                       hover:text-gray-700 dark:hover:text-slate-200
                       hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            <svg viewBox="0 0 20 20" fill="none" className="w-[18px] h-[18px]"
                 stroke="currentColor" strokeWidth="1.5">
              <path d="M3 5h14M3 10h14M3 15h14" strokeLinecap="round" />
            </svg>
          </button>

          <div className="flex-1 flex items-center justify-between min-w-0">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded bg-gradient-to-br from-pink-500 to-purple-500
                              flex items-center justify-center">
                <svg viewBox="0 0 16 16" fill="white" className="w-3.5 h-3.5">
                  <path d="M2 2h5v5H2V2zm7 0h5v5H9V2zm-7 7h5v5H2V9zm7 0h5v5H9V9z" />
                </svg>
              </div>
              <span className="font-semibold text-gray-950 dark:text-slate-100 tracking-tight">
                SEC EDGAR Research
              </span>
            </div>

            <div className="flex items-center gap-2">
              <ThemeToggle theme={theme} onToggle={toggle} />
              {page === "chat" && (
                <ModelPicker
                  value={model}
                  savedModels={savedModels}
                  onChange={setModel}
                  disabled={streaming}
                  role={user?.role}
                />
              )}
            </div>
          </div>
        </div>
      </header>

      {/* Page content */}
      {page === "admin" ? (
        <AdminPage />
      ) : page === "settings" ? (
        <SettingsPage
          models={savedModels}
          onAdd={handleAddModel}
          onDelete={handleDeleteModel}
        />
      ) : page === "about" ? (
        <AboutDataPage />
      ) : !streaming && !done && !error ? (
        <main className="max-w-3xl mx-auto px-4 w-full
                         min-h-[calc(100vh-57px)] flex flex-col items-center justify-center
                         gap-6 pb-20">
          <div className="text-center flex flex-col items-center gap-4">
            <div className="px-5 py-3 rounded-xl border border-gray-200 dark:border-slate-700
                            bg-white dark:bg-slate-900 shadow-sm">
              <img
                src="https://cdn.prod.website-files.com/689e69e2c321f4ef79561383/68a032ffd965e48cb2bf7a29_elizalogo-removebg-preview.png"
                alt="Eliza"
                className="h-8 w-auto dark:invert"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <h1 className="text-2xl font-semibold tracking-tight
                             text-gray-900 dark:text-slate-100">
                What would you like to know?
              </h1>
              <p className="text-sm text-gray-400 dark:text-slate-500">
                Search across 246 SEC filings from 54 companies
              </p>
            </div>
          </div>
          <div className="w-full">
            <QueryBox
              value={question}
              onChange={setQuestion}
              onSubmit={handleSubmit}
              loading={streaming}
            />
          </div>
        </main>
      ) : (
        <main className="max-w-3xl mx-auto px-4 py-8 flex flex-col gap-8">
          <QueryBox
            value={question}
            onChange={setQuestion}
            onSubmit={handleSubmit}
            loading={streaming}
          />

          {error && (
            <div className="flex items-start gap-3 rounded-lg px-4 py-3 text-sm
                            bg-red-50 border border-red-200 text-red-600
                            dark:bg-red-950/50 dark:border-red-800 dark:text-red-400">
              <span className="mt-0.5">⚠</span>
              <span>{error}</span>
            </div>
          )}

          {streamingText && (
            <>
              <div className="border-t border-gray-100 dark:border-slate-800" />
              <AnswerPanel
                text={streamingText}
                model={model}
                chunkCount={sources.length}
                activeIndex={activeIndex}
                onCitationClick={handleCitationClick}
                pending={streaming}
              />
            </>
          )}

          {sources.length > 0 && (
            <>
              <div className="border-t border-gray-100 dark:border-slate-800" />
              <SourceList sources={sources} activeIndex={activeIndex} />
            </>
          )}

          {streaming && !streamingText && (
            <div className="flex flex-col gap-4 animate-pulse">
              <div className="h-3 bg-gray-100 dark:bg-slate-800 rounded w-16" />
              <div className="flex flex-col gap-2">
                <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-full" />
                <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-5/6" />
                <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-4/6" />
                <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-full" />
                <div className="h-4 bg-gray-100 dark:bg-slate-800 rounded w-3/4" />
              </div>
            </div>
          )}
        </main>
      )}
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <ProtectedRoute>
        <AppInner />
      </ProtectedRoute>
    </AuthProvider>
  );
}

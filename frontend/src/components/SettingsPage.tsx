import { useState } from "react";
import type { SavedModel, Provider } from "../types";

interface Props {
  models: SavedModel[];
  onAdd: (model: SavedModel) => void;
  onDelete: (id: string) => void;
}

const PROVIDER_OPTIONS: { value: Provider; label: string; hint: string }[] = [
  { value: "openai",    label: "OpenAI",     hint: "e.g. gpt-4o, gpt-4o-mini" },
  { value: "anthropic", label: "Anthropic",  hint: "e.g. claude-opus-4-7, claude-sonnet-4-6" },
  { value: "local",     label: "Local Llama", hint: "e.g. llama3.2, mistral" },
];

const PROVIDER_COLOURS: Record<Provider, string> = {
  openai:    "bg-green-50 text-green-700 dark:bg-green-950/40 dark:text-green-400",
  anthropic: "bg-orange-50 text-orange-700 dark:bg-orange-950/40 dark:text-orange-400",
  local:     "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-400",
};

const DEFAULT_BASE_URL = "http://localhost:11434/v1";

function AddModelForm({ onSave }: { onSave: (m: SavedModel) => void }) {
  const [provider, setProvider]   = useState<Provider>("openai");
  const [apiKey, setApiKey]       = useState("");
  const [modelName, setModelName] = useState("");
  const [baseUrl, setBaseUrl]     = useState(DEFAULT_BASE_URL);

  const hint     = PROVIDER_OPTIONS.find((p) => p.value === provider)?.hint ?? "";
  const needsKey = provider !== "local";
  const canSave  = modelName.trim() && (!needsKey || apiKey.trim());

  function handleSave() {
    if (!canSave) return;
    onSave({
      id:        crypto.randomUUID(),
      provider,
      apiKey:    apiKey.trim(),
      modelName: modelName.trim(),
      baseUrl:   baseUrl.trim() || DEFAULT_BASE_URL,
    });
    setApiKey("");
    setModelName("");
    setBaseUrl(DEFAULT_BASE_URL);
  }

  return (
    <div className="rounded-xl border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-5 flex flex-col gap-4">
      <h3 className="text-sm font-semibold text-gray-900 dark:text-slate-100">Add model</h3>

      {/* Provider */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-slate-400">
          Provider
        </label>
        <div className="flex gap-2">
          {PROVIDER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setProvider(opt.value)}
              className={`flex-1 px-3 py-2 rounded-lg text-sm font-medium border transition-all
                ${provider === opt.value
                  ? "bg-pink-50 border-pink-400 text-pink-700 dark:bg-pink-950/40 dark:border-pink-600 dark:text-pink-400"
                  : "bg-white border-gray-200 text-gray-600 hover:border-gray-300 dark:bg-slate-800 dark:border-slate-700 dark:text-slate-400 dark:hover:border-slate-600"
                }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* API Key */}
      {needsKey && (
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-slate-400">
            API Key
          </label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={provider === "anthropic" ? "sk-ant-…" : "sk-…"}
            className="w-full rounded-lg px-3 py-2 text-sm
                       bg-white dark:bg-slate-800
                       border border-gray-200 dark:border-slate-700
                       text-gray-900 dark:text-slate-100
                       placeholder:text-gray-400 dark:placeholder:text-slate-500
                       focus:outline-none focus:ring-2 focus:ring-pink-400 focus:border-transparent"
          />
        </div>
      )}

      {/* Model name */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-slate-400">
          Model name
        </label>
        <input
          type="text"
          value={modelName}
          onChange={(e) => setModelName(e.target.value)}
          placeholder={hint}
          className="w-full rounded-lg px-3 py-2 text-sm
                     bg-white dark:bg-slate-800
                     border border-gray-200 dark:border-slate-700
                     text-gray-900 dark:text-slate-100
                     placeholder:text-gray-400 dark:placeholder:text-slate-500
                     focus:outline-none focus:ring-2 focus:ring-pink-400 focus:border-transparent"
        />
      </div>

      {/* Base URL */}
      {provider === "local" && (
        <div className="flex flex-col gap-1.5">
          <label className="text-xs font-medium uppercase tracking-wider text-gray-500 dark:text-slate-400">
            Base URL
          </label>
          <input
            type="text"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={DEFAULT_BASE_URL}
            className="w-full rounded-lg px-3 py-2 text-sm font-mono
                       bg-white dark:bg-slate-800
                       border border-gray-200 dark:border-slate-700
                       text-gray-900 dark:text-slate-100
                       placeholder:text-gray-400 dark:placeholder:text-slate-500
                       focus:outline-none focus:ring-2 focus:ring-pink-400 focus:border-transparent"
          />
        </div>
      )}

      <button
        onClick={handleSave}
        disabled={!canSave}
        className="self-end px-5 py-2 rounded-lg text-sm font-semibold
                   bg-gradient-to-r from-pink-500 to-purple-500 text-white shadow-sm
                   hover:from-pink-600 hover:to-purple-600 transition-all
                   disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Save model
      </button>
    </div>
  );
}

export default function SettingsPage({ models, onAdd, onDelete }: Props) {
  return (
    <main className="max-w-3xl mx-auto px-4 py-8 flex flex-col gap-8">
        {/* Registered models */}
        <section className="flex flex-col gap-4">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-slate-500">
            Registered models{" "}
            <span className="font-normal normal-case tracking-normal text-gray-300 dark:text-slate-600">
              ({models.length})
            </span>
          </h2>

          {models.length === 0 && (
            <p className="text-sm text-gray-400 dark:text-slate-500">
              No custom models yet. Add one below.
            </p>
          )}

          {models.map((m) => (
            <div
              key={m.id}
              className="flex items-center gap-3 rounded-xl border border-gray-200 dark:border-slate-700
                         bg-white dark:bg-slate-900 px-4 py-3"
            >
              <span className={`text-xs font-semibold px-2 py-0.5 rounded ${PROVIDER_COLOURS[m.provider]}`}>
                {m.provider}
              </span>
              <span className="text-sm font-medium text-gray-800 dark:text-slate-200 flex-1">
                {m.modelName}
              </span>
              {m.provider !== "local" && (
                <span className="text-xs text-gray-400 dark:text-slate-500 font-mono">
                  {m.apiKey ? `${m.apiKey.slice(0, 8)}…` : "no key"}
                </span>
              )}
              {m.provider === "local" && (
                <span className="text-xs text-gray-400 dark:text-slate-500 font-mono truncate max-w-[160px]">
                  {m.baseUrl}
                </span>
              )}
              <button
                onClick={() => onDelete(m.id)}
                className="ml-2 p-1.5 rounded-lg text-gray-400 dark:text-slate-500
                           hover:text-red-500 dark:hover:text-red-400
                           hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
                title="Remove"
              >
                <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5" stroke="currentColor" strokeWidth="1.5">
                  <path d="M3 4h10M6 4V2.5a.5.5 0 01.5-.5h3a.5.5 0 01.5.5V4M5 4l.5 9h5l.5-9" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
            </div>
          ))}
        </section>

        <div className="border-t border-gray-100 dark:border-slate-800" />

        {/* Add form */}
        <AddModelForm onSave={onAdd} />
    </main>
  );
}

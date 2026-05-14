import { useRef, useEffect, KeyboardEvent } from "react";

interface Props {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading: boolean;
}

const EXAMPLES = [
  "What are Apple's primary risk factors?",
  "How has NVIDIA's revenue changed over the last two years?",
  "Compare the risk factors facing Apple, Tesla, and JPMorgan.",
  "What regulatory risks do major pharmaceutical companies face?",
];

export default function QueryBox({ value, onChange, onSubmit, loading }: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [value]);

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (!loading && value.trim()) onSubmit();
    }
  }

  return (
    <div className="w-full">
      <div className="relative flex items-end gap-3 p-3 rounded-xl shadow-sm transition-all
                      bg-white dark:bg-slate-900
                      border border-gray-200 dark:border-slate-700
                      focus-within:border-pink-400 dark:focus-within:border-pink-500
                      focus-within:ring-1 focus-within:ring-pink-400 dark:focus-within:ring-pink-500">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask a question about SEC filings…"
          rows={1}
          disabled={loading}
          className="flex-1 resize-none bg-transparent text-base leading-relaxed
                     focus:outline-none disabled:opacity-60 min-h-[40px] max-h-48 overflow-y-auto
                     text-gray-900 dark:text-slate-100
                     placeholder-gray-300 dark:placeholder-slate-600"
        />
        <button
          onClick={onSubmit}
          disabled={loading || !value.trim()}
          className="flex-shrink-0 flex items-center gap-2 px-4 py-2 rounded-lg
                     text-sm font-medium transition-all shadow-sm
                     bg-gradient-to-r from-pink-500 to-purple-500
                     hover:from-pink-600 hover:to-purple-600
                     text-white
                     disabled:from-gray-200 disabled:to-gray-200 disabled:text-gray-400
                     dark:disabled:from-slate-700 dark:disabled:to-slate-700 dark:disabled:text-slate-500"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <Spinner />
              Thinking…
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              Ask
              <kbd className="hidden sm:inline-flex items-center text-xs opacity-70 font-mono
                              bg-white/20 px-1.5 py-0.5 rounded">
                ⌘↵
              </kbd>
            </span>
          )}
        </button>
      </div>

      {!value && (
        <div className="mt-4 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => onChange(ex)}
              className="text-xs rounded-full px-3 py-1.5 transition-colors
                         bg-white dark:bg-slate-900
                         border border-gray-200 dark:border-slate-700
                         text-gray-500 dark:text-slate-400
                         hover:border-pink-300 dark:hover:border-pink-700
                         hover:text-pink-600 dark:hover:text-pink-400
                         hover:bg-pink-50 dark:hover:bg-pink-950/30"
            >
              {ex}
            </button>
          ))}
        </div>
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

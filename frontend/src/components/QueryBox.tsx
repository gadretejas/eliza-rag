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

  // Auto-resize textarea
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
      <div className="relative flex items-end gap-3 bg-slate-900 border border-slate-700 rounded-xl p-3
                      focus-within:border-blue-500 transition-colors">
        <textarea
          ref={ref}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder="Ask a question about SEC filings…"
          rows={1}
          disabled={loading}
          className="flex-1 resize-none bg-transparent text-slate-100 placeholder-slate-500 text-base
                     leading-relaxed focus:outline-none disabled:opacity-60 min-h-[40px] max-h-48 overflow-y-auto"
        />
        <button
          onClick={onSubmit}
          disabled={loading || !value.trim()}
          className="flex-shrink-0 flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500
                     disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-medium
                     rounded-lg transition-colors"
        >
          {loading ? (
            <span className="flex items-center gap-2">
              <Spinner />
              Thinking…
            </span>
          ) : (
            <span className="flex items-center gap-1.5">
              Ask
              <kbd className="hidden sm:inline-flex items-center text-xs opacity-60 font-mono bg-blue-700 px-1.5 py-0.5 rounded">
                ⌘↵
              </kbd>
            </span>
          )}
        </button>
      </div>

      {/* Example questions — shown only when input is empty */}
      {!value && (
        <div className="mt-4 flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => onChange(ex)}
              className="text-xs text-slate-400 border border-slate-700 hover:border-slate-500
                         hover:text-slate-300 rounded-full px-3 py-1.5 transition-colors"
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
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

import { useState, useEffect, useRef } from "react";
import type { Source } from "../types";
import TickerBadge from "./TickerBadge";

interface Props {
  source: Source;
  highlighted: boolean;
}

export default function SourceCard({ source, highlighted }: Props) {
  const [expanded, setExpanded] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (highlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [highlighted]);

  const shortFilingType = source.filing_type.split(" ")[0];

  return (
    <div
      ref={ref}
      className={`rounded-xl border transition-all duration-200
                  bg-white dark:bg-slate-900
                  ${highlighted
                    ? "border-pink-400 dark:border-pink-600 shadow-md shadow-pink-100/50 dark:shadow-pink-900/20 ring-1 ring-pink-300 dark:ring-pink-700"
                    : "border-gray-200 dark:border-slate-700 shadow-sm hover:border-gray-300 dark:hover:border-slate-600 hover:shadow-md"
                  }`}
    >
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        <span className="flex-shrink-0 w-6 h-6 rounded text-xs font-semibold flex items-center justify-center
                         bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400">
          {source.index}
        </span>

        <TickerBadge ticker={source.ticker} />

        <span className="text-xs font-medium rounded px-2 py-0.5
                         bg-gray-100 dark:bg-slate-800 text-gray-500 dark:text-slate-400">
          {shortFilingType}
        </span>

        <span className="text-xs text-gray-400 dark:text-slate-500">{source.filing_date}</span>

        <span className="text-xs font-mono text-gray-400 dark:text-slate-500">{source.section}</span>

        <span className="ml-auto text-xs text-gray-300 dark:text-slate-600">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-gray-100 dark:border-slate-800">
          <p className="text-sm font-mono leading-relaxed whitespace-pre-wrap
                        text-gray-600 dark:text-slate-400">
            {source.snippet}
            {source.snippet.length >= 400 && (
              <span className="text-gray-400 dark:text-slate-600"> …</span>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

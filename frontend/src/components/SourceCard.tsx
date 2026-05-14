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

  // Scroll into view when highlighted by a citation click
  useEffect(() => {
    if (highlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [highlighted]);

  const shortFilingType = source.filing_type.split(" ")[0]; // "10-K" from "10-K (Annual Report)"

  return (
    <div
      ref={ref}
      className={`rounded-lg border bg-slate-900 transition-all duration-200
                  ${highlighted ? "border-blue-500 shadow-lg shadow-blue-500/10" : "border-slate-800 hover:border-slate-700"}`}
    >
      <button
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
      >
        {/* Index badge */}
        <span className="flex-shrink-0 w-6 h-6 rounded bg-slate-700 text-slate-300 text-xs font-semibold flex items-center justify-center">
          {source.index}
        </span>

        <TickerBadge ticker={source.ticker} />

        <span className="text-xs font-medium text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
          {shortFilingType}
        </span>

        <span className="text-xs text-slate-500">{source.filing_date}</span>

        <span className="text-xs text-slate-600 font-mono">{source.section}</span>

        <span className="ml-auto text-slate-600 text-xs">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pt-1 border-t border-slate-800">
          <p className="text-sm text-slate-400 leading-relaxed font-mono whitespace-pre-wrap">
            {source.snippet}
            {source.snippet.length >= 400 && (
              <span className="text-slate-600"> …</span>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

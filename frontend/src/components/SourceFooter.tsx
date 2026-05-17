import type { Source } from "../types";
import TickerBadge from "./TickerBadge";

interface Props {
  sources:     Source[];
  onChipClick: (representative: Source, fileChunks: Source[]) => void;
}

export default function SourceFooter({ sources, onChipClick }: Props) {
  if (!sources.length) return null;

  // Deduplicate by (ticker, filing_type, filing_date, section)
  const seen   = new Set<string>();
  const unique: Source[] = [];
  for (const s of sources) {
    const key = `${s.ticker}|${s.filing_type}|${s.filing_date}|${s.section}`;
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(s);
    }
  }

  function chunksForFile(rep: Source): Source[] {
    return sources.filter(
      (s) =>
        s.ticker       === rep.ticker &&
        s.filing_type  === rep.filing_type &&
        s.filing_date  === rep.filing_date &&
        s.section      === rep.section,
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-semibold uppercase tracking-widest
                       text-gray-400 dark:text-slate-500 flex-shrink-0">
        Sources
      </span>
      {unique.map((s) => (
        <button
          key={`${s.ticker}|${s.filing_type}|${s.filing_date}|${s.section}`}
          onClick={() => onChipClick(s, chunksForFile(s))}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs
                     border border-gray-200 dark:border-slate-700
                     bg-white dark:bg-slate-900
                     hover:border-pink-300 dark:hover:border-pink-700
                     hover:bg-pink-50 dark:hover:bg-pink-950/30
                     text-gray-600 dark:text-slate-400
                     hover:text-pink-700 dark:hover:text-pink-300
                     transition-colors"
        >
          <TickerBadge ticker={s.ticker} />
          <span className="font-medium text-gray-500 dark:text-slate-400">
            {s.filing_type.split(" ")[0]}
          </span>
          <span className="text-gray-400 dark:text-slate-500">{s.filing_date}</span>
          <span className="font-mono text-gray-400 dark:text-slate-500">{s.section}</span>
        </button>
      ))}
    </div>
  );
}

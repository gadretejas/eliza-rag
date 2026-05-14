const SECTOR_COLOURS: Record<string, string> = {
  AAPL: "bg-blue-900 text-blue-300",
  MSFT: "bg-blue-900 text-blue-300",
  NVDA: "bg-green-900 text-green-300",
  AMD:  "bg-green-900 text-green-300",
  INTC: "bg-green-900 text-green-300",
  META: "bg-blue-900 text-blue-300",
  GOOG: "bg-blue-900 text-blue-300",
  AMZN: "bg-blue-900 text-blue-300",
  TSLA: "bg-red-900 text-red-300",
  JPM:  "bg-amber-900 text-amber-300",
  GS:   "bg-amber-900 text-amber-300",
  MS:   "bg-amber-900 text-amber-300",
  BAC:  "bg-amber-900 text-amber-300",
  PFE:  "bg-teal-900 text-teal-300",
  JNJ:  "bg-teal-900 text-teal-300",
  MRK:  "bg-teal-900 text-teal-300",
  LLY:  "bg-teal-900 text-teal-300",
  ABBV: "bg-teal-900 text-teal-300",
  XOM:  "bg-orange-900 text-orange-300",
  CVX:  "bg-orange-900 text-orange-300",
};

interface Props {
  ticker: string;
}

export default function TickerBadge({ ticker }: Props) {
  const colour = SECTOR_COLOURS[ticker] ?? "bg-slate-700 text-slate-300";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold tracking-wide ${colour}`}>
      {ticker}
    </span>
  );
}

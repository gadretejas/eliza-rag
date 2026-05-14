const SECTOR_COLOURS: Record<string, string> = {
  // Tech
  AAPL: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  MSFT: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  ADBE: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  ORCL: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  CRM:  "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  CSCO: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  IBM:  "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  NFLX: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  META: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  GOOG: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  AMZN: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
  // Semiconductors
  NVDA: "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-400",
  AMD:  "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-400",
  INTC: "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-400",
  // Healthcare / Pharma
  PFE:  "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  JNJ:  "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  MRK:  "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  LLY:  "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  ABBV: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  UNH:  "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  TMO:  "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
  // Finance
  JPM:  "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  GS:   "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  MS:   "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  BAC:  "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  BLK:  "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  AXP:  "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  MA:   "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  V:    "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  BRK:  "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
  // Energy
  XOM:  "bg-orange-50 text-orange-700 dark:bg-orange-950/40 dark:text-orange-400",
  CVX:  "bg-orange-50 text-orange-700 dark:bg-orange-950/40 dark:text-orange-400",
  // Automotive
  TSLA: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400",
};

interface Props {
  ticker: string;
}

export default function TickerBadge({ ticker }: Props) {
  const colour = SECTOR_COLOURS[ticker] ?? "bg-gray-100 text-gray-700 dark:bg-slate-800 dark:text-slate-300";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold tracking-wide ${colour}`}>
      {ticker}
    </span>
  );
}

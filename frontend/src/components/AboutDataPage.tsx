const SECTORS = [
  {
    name: "Technology",
    colour: "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-400",
    tickers: ["AAPL", "MSFT", "GOOG", "META", "AMZN", "ADBE", "CRM", "CSCO", "IBM", "NFLX", "ORCL"],
  },
  {
    name: "Semiconductors",
    colour: "bg-violet-50 text-violet-700 dark:bg-violet-950/40 dark:text-violet-400",
    tickers: ["NVDA", "AMD", "INTC"],
  },
  {
    name: "Healthcare & Pharma",
    colour: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400",
    tickers: ["UNH", "LLY", "JNJ", "ABBV", "MRK", "PFE", "TMO"],
  },
  {
    name: "Financial Services",
    colour: "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400",
    tickers: ["BRK", "JPM", "V", "MA", "BAC", "GS", "MS", "BLK", "AXP"],
  },
  {
    name: "Retail & Consumer",
    colour: "bg-pink-50 text-pink-700 dark:bg-pink-950/40 dark:text-pink-400",
    tickers: ["WMT", "COST", "HD", "TGT", "MCD", "SBUX", "NKE", "PG", "KO", "PEP"],
  },
  {
    name: "Industrial & Defense",
    colour: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
    tickers: ["CAT", "DE", "BA", "LMT", "RTX", "GE", "UPS"],
  },
  {
    name: "Energy",
    colour: "bg-orange-50 text-orange-700 dark:bg-orange-950/40 dark:text-orange-400",
    tickers: ["XOM", "CVX"],
  },
  {
    name: "Telecom & Media",
    colour: "bg-cyan-50 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-400",
    tickers: ["T", "VZ", "CMCSA", "DIS"],
  },
  {
    name: "Automotive",
    colour: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400",
    tickers: ["TSLA"],
  },
];

const STATS = [
  { value: "54", label: "Companies" },
  { value: "246", label: "Total filings" },
  { value: "89", label: "Annual reports (10-K)" },
  { value: "157", label: "Quarterly reports (10-Q)" },
  { value: "2022–2026", label: "Primary coverage" },
  { value: "9", label: "Sectors" },
];

export default function AboutDataPage() {
  return (
    <main className="max-w-3xl mx-auto px-4 py-8 flex flex-col gap-8">

      {/* Intro */}
      <section className="flex flex-col gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-slate-500">
          About the data
        </h2>
        <p className="text-sm text-gray-600 dark:text-slate-400 leading-relaxed">
          This corpus is built from SEC EDGAR filings for 54 of the largest publicly traded US companies.
          All documents were downloaded directly from EDGAR, chunked by section, embedded, and stored in a
          local vector database. Retrieval combines dense semantic search with metadata filtering so
          questions about specific companies, filing types, or time periods are answered from the
          most relevant passages.
        </p>
      </section>

      <div className="border-t border-gray-100 dark:border-slate-800" />

      {/* Stats grid */}
      <section className="flex flex-col gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-slate-500">
          At a glance
        </h2>
        <div className="grid grid-cols-3 gap-3">
          {STATS.map((s) => (
            <div key={s.label}
                 className="rounded-xl border border-gray-200 dark:border-slate-700
                            bg-white dark:bg-slate-900 px-4 py-3 flex flex-col gap-0.5">
              <span className="text-xl font-bold text-gray-900 dark:text-slate-100 tracking-tight">
                {s.value}
              </span>
              <span className="text-xs text-gray-500 dark:text-slate-400">{s.label}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="border-t border-gray-100 dark:border-slate-800" />

      {/* Filing types */}
      <section className="flex flex-col gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-slate-500">
          Filing types
        </h2>
        <div className="flex flex-col gap-3">
          <div className="rounded-xl border border-gray-200 dark:border-slate-700
                          bg-white dark:bg-slate-900 px-4 py-3 flex flex-col gap-1">
            <span className="text-sm font-semibold text-gray-800 dark:text-slate-200">10-K — Annual Report</span>
            <p className="text-xs text-gray-500 dark:text-slate-400 leading-relaxed">
              Comprehensive yearly filing covering business overview, risk factors (Item 1A),
              financial statements, and management discussion. Best source for strategic and
              risk-related questions.
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 dark:border-slate-700
                          bg-white dark:bg-slate-900 px-4 py-3 flex flex-col gap-1">
            <span className="text-sm font-semibold text-gray-800 dark:text-slate-200">10-Q — Quarterly Report</span>
            <p className="text-xs text-gray-500 dark:text-slate-400 leading-relaxed">
              Filed three times per year (Q1–Q3). Contains updated financials and any material
              changes since the last annual report. Best for tracking recent revenue, earnings,
              and short-term developments.
            </p>
          </div>
        </div>
      </section>

      <div className="border-t border-gray-100 dark:border-slate-800" />

      {/* Sectors */}
      <section className="flex flex-col gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-slate-500">
          Companies by sector
        </h2>
        <div className="flex flex-col gap-3">
          {SECTORS.map((sector) => (
            <div key={sector.name}
                 className="rounded-xl border border-gray-200 dark:border-slate-700
                            bg-white dark:bg-slate-900 px-4 py-3 flex flex-col gap-2">
              <span className="text-xs font-semibold text-gray-600 dark:text-slate-400">
                {sector.name}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {sector.tickers.map((t) => (
                  <span key={t}
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold tracking-wide ${sector.colour}`}>
                    {t}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Footer note */}
      <p className="text-xs text-gray-400 dark:text-slate-600 pb-4">
        Filings were retrieved from SEC EDGAR (sec.gov). This tool is for research purposes only
        and does not constitute financial or investment advice.
      </p>
    </main>
  );
}

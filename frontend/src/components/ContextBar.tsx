interface Props {
  tokensUsed:   number;
  contextLimit: number;
}

function fmt(n: number): string {
  return n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : String(n);
}

export default function ContextBar({ tokensUsed, contextLimit }: Props) {
  const pct     = contextLimit > 0 ? Math.min(tokensUsed / contextLimit, 1) : 0;
  const percent = Math.round(pct * 100);

  const isWarning  = pct >= 0.9 && pct < 1;
  const isExhausted = pct >= 1;

  const barColor = isExhausted
    ? "bg-red-500"
    : isWarning
    ? "bg-amber-400"
    : "bg-emerald-400";

  const textColor = isExhausted
    ? "text-red-600 dark:text-red-400"
    : isWarning
    ? "text-amber-600 dark:text-amber-400"
    : "text-gray-400 dark:text-slate-500";

  return (
    <div className="flex flex-col gap-1">
      {/* Bar + label */}
      <div className="flex items-center gap-2">
        <div className="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-300 ${barColor}`}
            style={{ width: `${percent}%` }}
          />
        </div>
        <span className={`text-[11px] font-mono flex-shrink-0 ${textColor}`}>
          {fmt(tokensUsed)} / {fmt(contextLimit)}
        </span>
      </div>

      {/* Warning banners */}
      {isExhausted && (
        <p className="text-xs text-red-600 dark:text-red-400 font-medium">
          Context limit reached — no more messages can be sent.
        </p>
      )}
      {isWarning && (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Approaching context limit — consider starting a new chat soon.
        </p>
      )}
    </div>
  );
}

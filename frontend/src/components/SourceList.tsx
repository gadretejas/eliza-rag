import type { Source } from "../types";
import SourceCard from "./SourceCard";

interface Props {
  sources: Source[];
  activeIndex: number | null;
}

export default function SourceList({ sources, activeIndex }: Props) {
  if (!sources.length) return null;

  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500 mb-3">
        Sources <span className="text-slate-700 font-normal normal-case tracking-normal">({sources.length})</span>
      </h2>
      <div className="flex flex-col gap-2">
        {sources.map((s) => (
          <SourceCard
            key={s.index}
            source={s}
            highlighted={activeIndex === s.index}
          />
        ))}
      </div>
    </section>
  );
}

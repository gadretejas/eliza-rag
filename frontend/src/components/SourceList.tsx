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
      <h2 className="text-xs font-semibold uppercase tracking-widest mb-3
                     text-gray-400 dark:text-slate-500">
        Sources{" "}
        <span className="font-normal normal-case tracking-normal text-gray-300 dark:text-slate-600">
          ({sources.length})
        </span>
      </h2>
      <div className="flex flex-col gap-3">
        {sources.map((s) => (
          <SourceCard key={s.index} source={s} highlighted={activeIndex === s.index} />
        ))}
      </div>
    </section>
  );
}

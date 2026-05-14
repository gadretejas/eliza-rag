import CitationChip from "./CitationChip";

interface Props {
  text: string;
  model: string;
  chunkCount: number;
  activeIndex: number | null;
  onCitationClick: (index: number) => void;
  pending?: boolean;
}

export default function AnswerPanel({ text, model, chunkCount, activeIndex, onCitationClick, pending = false }: Props) {
  const nodes = renderWithCitations(text, activeIndex, onCitationClick, pending);

  return (
    <section>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-slate-500">
          Answer
        </h2>
        <span className="text-xs text-gray-400 dark:text-slate-500">
          {model} · {chunkCount} chunks
        </span>
      </div>
      <div className="text-gray-800 dark:text-slate-200 leading-relaxed text-[15px]">{nodes}</div>
    </section>
  );
}

function renderWithCitations(
  text: string,
  activeIndex: number | null,
  onCitationClick: (i: number) => void,
  pending: boolean,
) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (match) {
      const idx = parseInt(match[1], 10);
      return (
        <CitationChip
          key={i}
          index={idx}
          active={!pending && activeIndex === idx}
          onClick={pending ? undefined : () => onCitationClick(idx)}
          pending={pending}
        />
      );
    }
    return <FormattedText key={i} text={part} />;
  });
}

function FormattedText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, li) => {
        const segments = line.split(/(\*\*[^*]+\*\*)/g);
        const rendered = segments.map((seg, si) => {
          if (seg.startsWith("**") && seg.endsWith("**")) {
            return (
              <strong key={si} className="text-gray-900 dark:text-slate-100 font-semibold">
                {seg.slice(2, -2)}
              </strong>
            );
          }
          return <span key={si}>{seg}</span>;
        });
        return (
          <span key={li}>
            {rendered}
            {li < lines.length - 1 && <br />}
          </span>
        );
      })}
    </>
  );
}

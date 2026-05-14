interface Props {
  index: number;
  active: boolean;
  onClick: () => void;
}

export default function CitationChip({ index, active, onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center justify-center w-5 h-5 rounded text-xs font-semibold
                  mx-0.5 align-middle transition-colors
                  ${active
                    ? "bg-blue-500 text-white"
                    : "bg-slate-700 text-slate-300 hover:bg-blue-600 hover:text-white"
                  }`}
    >
      {index}
    </button>
  );
}

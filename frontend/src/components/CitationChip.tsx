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
                  mx-0.5 align-middle transition-colors border
                  ${active
                    ? "bg-pink-600 text-white border-transparent dark:bg-pink-500"
                    : "bg-pink-50 text-pink-600 border-pink-200 hover:bg-pink-600 hover:text-white hover:border-transparent dark:bg-pink-950/40 dark:text-pink-400 dark:border-pink-800 dark:hover:bg-pink-500 dark:hover:text-white"
                  }`}
    >
      {index}
    </button>
  );
}

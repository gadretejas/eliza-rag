interface Props {
  index: number;
  active: boolean;
  onClick?: () => void;
  pending?: boolean;
}

export default function CitationChip({ index, active, onClick, pending = false }: Props) {
  return (
    <button
      onClick={onClick}
      disabled={pending}
      className={`inline-flex items-center justify-center w-5 h-5 rounded text-xs font-semibold
                  mx-0.5 align-middle transition-colors border
                  ${pending
                    ? "bg-gray-100 text-gray-400 border-gray-200 cursor-default dark:bg-slate-800 dark:text-slate-500 dark:border-slate-700"
                    : active
                      ? "bg-pink-600 text-white border-transparent dark:bg-pink-500"
                      : "bg-pink-50 text-pink-600 border-pink-200 hover:bg-pink-600 hover:text-white hover:border-transparent dark:bg-pink-950/40 dark:text-pink-400 dark:border-pink-800 dark:hover:bg-pink-500 dark:hover:text-white"
                  }`}
    >
      {index}
    </button>
  );
}

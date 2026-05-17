interface Props {
  onClick: () => void;
  loading?: boolean;
}

export default function FollowUpButton({ onClick, loading = false }: Props) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm
                 font-medium border transition-colors
                 border-pink-300 dark:border-pink-700
                 text-pink-600 dark:text-pink-400
                 hover:bg-pink-50 dark:hover:bg-pink-950/30
                 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5"
           stroke="currentColor" strokeWidth="1.5">
        <path d="M2 8a6 6 0 1 0 6-6" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M2 4v4h4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {loading ? "Starting…" : "Follow up"}
    </button>
  );
}

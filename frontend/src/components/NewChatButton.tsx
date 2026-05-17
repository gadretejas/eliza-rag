interface Props {
  onClick: () => void;
}

export default function NewChatButton({ onClick }: Props) {
  return (
    <button
      onClick={onClick}
      title="New chat"
      className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium
                 text-gray-500 dark:text-slate-400
                 hover:text-gray-800 dark:hover:text-slate-100
                 hover:bg-gray-100 dark:hover:bg-slate-800
                 transition-colors"
    >
      <svg viewBox="0 0 16 16" fill="none" className="w-3.5 h-3.5"
           stroke="currentColor" strokeWidth="1.5">
        <path d="M8 3H3a1 1 0 00-1 1v9a1 1 0 001 1h9a1 1 0 001-1V9"
              strokeLinecap="round" strokeLinejoin="round" />
        <path d="M12 1l3 3-6 6H6V7l6-6z"
              strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      New chat
    </button>
  );
}

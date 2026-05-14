type Page = "chat" | "about" | "settings";

interface Props {
  open: boolean;
  currentPage: Page;
  onNavigate: (page: Page) => void;
  onClose: () => void;
}

const NAV_ITEMS: { page: Page; label: string; icon: React.ReactNode }[] = [
  {
    page: "chat",
    label: "Chat",
    icon: (
      <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
        <path d="M2 4.5A1.5 1.5 0 013.5 3h13A1.5 1.5 0 0118 4.5v9a1.5 1.5 0 01-1.5 1.5H11l-3 3v-3H3.5A1.5 1.5 0 012 13.5v-9z"
              strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    page: "about",
    label: "About data",
    icon: (
      <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
        <circle cx="10" cy="10" r="7.5" />
        <path d="M10 9v5M10 6.5v.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  {
    page: "settings",
    label: "Settings",
    icon: (
      <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
        <circle cx="10" cy="10" r="2.5" />
        <path d="M10 2v1.5M10 16.5V18M2 10h1.5M16.5 10H18M4.1 4.1l1.06 1.06M14.84 14.84l1.06 1.06M4.1 15.9l1.06-1.06M14.84 5.16l1.06-1.06"
              strokeLinecap="round" />
      </svg>
    ),
  },
];

export default function Sidebar({ open, currentPage, onNavigate, onClose }: Props) {
  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 bg-black/20 dark:bg-black/50 backdrop-blur-sm
                    transition-opacity duration-200
                    ${open ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
        onClick={onClose}
      />

      {/* Panel */}
      <aside
        className={`fixed top-0 left-0 z-50 h-full w-56
                    bg-gray-50 dark:bg-slate-900
                    border-r border-gray-200 dark:border-slate-700
                    shadow-2xl flex flex-col
                    transition-transform duration-200 ease-in-out
                    ${open ? "translate-x-0" : "-translate-x-full"}`}
      >
        {/* Panel header */}
        <div className="flex items-center justify-between px-4 py-3
                        border-b border-gray-200 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <div className="w-5 h-5 rounded bg-gradient-to-br from-pink-500 to-purple-500
                            flex items-center justify-center flex-shrink-0">
              <svg viewBox="0 0 16 16" fill="white" className="w-3 h-3">
                <path d="M2 2h5v5H2V2zm7 0h5v5H9V2zm-7 7h5v5H2V9zm7 0h5v5H9V9z" />
              </svg>
            </div>
            <span className="text-sm font-semibold text-gray-900 dark:text-slate-100 tracking-tight">
              SEC EDGAR
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-gray-400 dark:text-slate-500
                       hover:text-gray-700 dark:hover:text-slate-200
                       hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            <svg viewBox="0 0 16 16" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 3l10 10M13 3L3 13" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-2 py-3 flex flex-col gap-0.5">
          {NAV_ITEMS.map(({ page, label, icon }) => (
            <button
              key={page}
              onClick={() => { onNavigate(page); onClose(); }}
              className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm
                          font-medium transition-colors text-left
                          ${currentPage === page
                            ? "bg-pink-50 text-pink-700 dark:bg-pink-950/40 dark:text-pink-400"
                            : "text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 hover:text-gray-900 dark:hover:text-slate-100"
                          }`}
            >
              {icon}
              {label}
            </button>
          ))}
        </nav>
      </aside>
    </>
  );
}

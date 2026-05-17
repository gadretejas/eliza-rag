import { useEffect, useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { getRecentHistory } from "../api";
import type { ConversationSummary } from "../types";

type Page = "chat" | "about" | "settings" | "admin" | "history";

interface Props {
  open:          boolean;
  currentPage:   Page;
  onNavigate:    (page: Page) => void;
  onClose:       () => void;
  onSelectChat?: (id: number) => void;
}

export default function Sidebar({ open, currentPage, onNavigate, onClose, onSelectChat }: Props) {
  const { user, logout, isAdmin } = useAuth();
  const [recentChats, setRecentChats] = useState<ConversationSummary[]>([]);

  // Refresh recent chats each time the sidebar opens
  useEffect(() => {
    if (!open) return;
    getRecentHistory()
      .then((data) => setRecentChats(data.items))
      .catch(() => setRecentChats([]));
  }, [open]);

  const NAV_ITEMS: { page: Page; label: string; adminOnly?: boolean; icon: React.ReactNode }[] = [
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
      page: "history",
      label: "History",
      icon: (
        <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
          <path d="M10 6v4l2.5 2.5M10 17.5a7.5 7.5 0 100-15 7.5 7.5 0 000 15z"
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
        <svg viewBox="0 0 24 24" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
          <path strokeLinecap="round" strokeLinejoin="round"
            d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
        </svg>
      ),
    },
    {
      page:      "admin",
      label:     "Admin",
      adminOnly: true,
      icon: (
        <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
          <path d="M10 2a4 4 0 100 8 4 4 0 000-8zM4 14a6 6 0 0112 0v1H4v-1z"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ),
    },
  ];

  const visibleItems = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin);

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
        <nav className="flex-1 px-2 py-3 flex flex-col gap-0.5 overflow-y-auto">
          {visibleItems.map(({ page, label, icon }) => (
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

          {/* Recent chats */}
          {recentChats.length > 0 && (
            <div className="mt-3">
              <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-wider
                            text-gray-400 dark:text-slate-500">
                Recent
              </p>
              {recentChats.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    if (onSelectChat) onSelectChat(c.id);
                    onNavigate("history");
                    onClose();
                  }}
                  title={c.title}
                  className="w-full text-left px-3 py-1.5 rounded-lg text-xs
                             text-gray-600 dark:text-slate-400
                             hover:bg-gray-100 dark:hover:bg-slate-800
                             hover:text-gray-900 dark:hover:text-slate-100
                             truncate transition-colors"
                >
                  {c.title}
                </button>
              ))}
            </div>
          )}
        </nav>

        {/* User info + logout */}
        <div className="px-3 py-3 border-t border-gray-200 dark:border-slate-800 flex flex-col gap-2">
          {user && (
            <div className="px-2 py-1.5">
              <p className="text-xs font-medium text-gray-700 dark:text-slate-300 truncate">
                {user.email}
              </p>
              <p className="text-xs text-gray-400 dark:text-slate-500 capitalize">
                {user.role}
              </p>
            </div>
          )}
          <button
            onClick={() => { logout(); onClose(); }}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm
                       font-medium text-gray-500 dark:text-slate-400
                       hover:bg-red-50 dark:hover:bg-red-950/30
                       hover:text-red-600 dark:hover:text-red-400
                       transition-colors text-left"
          >
            <svg viewBox="0 0 20 20" fill="none" className="w-4 h-4" stroke="currentColor" strokeWidth="1.5">
              <path d="M13 10H3m0 0l3-3m-3 3l3 3M8 6V4a1 1 0 011-1h7a1 1 0 011 1v12a1 1 0 01-1 1H9a1 1 0 01-1-1v-2"
                    strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Sign out
          </button>
        </div>
      </aside>
    </>
  );
}

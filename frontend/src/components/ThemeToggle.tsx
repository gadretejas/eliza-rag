interface Props {
  theme: "light" | "dark";
  onToggle: () => void;
}

export default function ThemeToggle({ theme, onToggle }: Props) {
  return (
    <button
      onClick={onToggle}
      title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
      className="w-8 h-8 flex items-center justify-center rounded-lg border border-gray-200
                 dark:border-slate-700 bg-white dark:bg-slate-900
                 text-gray-500 dark:text-slate-400
                 hover:border-pink-300 dark:hover:border-pink-700
                 hover:text-pink-600 dark:hover:text-pink-400
                 transition-colors"
    >
      {theme === "light" ? <MoonIcon /> : <SunIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4.22 1.78a1 1 0 011.415 1.415l-.707.707a1 1 0 11-1.414-1.414l.707-.707zM18 9a1 1 0 110 2h-1a1 1 0 110-2h1zM4.22 15.78a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414l-.707.707zM2 10a1 1 0 100 2h1a1 1 0 100-2H2zm2.22-5.78a1 1 0 010 1.414l-.707.707A1 1 0 012.1 4.93l.707-.707a1 1 0 011.414 0zM10 6a4 4 0 100 8 4 4 0 000-8zm6.485 9.071a1 1 0 01-1.414 0l-.707-.707a1 1 0 011.414-1.414l.707.707a1 1 0 010 1.414z" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
    </svg>
  );
}

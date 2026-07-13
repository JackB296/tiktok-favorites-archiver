import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Link } from "react-router-dom";
import { FilmReel, SquaresFour, DownloadSimple, Sun, Moon, BookmarkSimple } from "@phosphor-icons/react";
import { Viewer } from "./routes/Viewer";
import { Gallery } from "./routes/Gallery";
import { Dashboard } from "./routes/Dashboard";
import { cx } from "./components/ui";

const TABS = [
  { to: "/", label: "Feed", icon: FilmReel, end: true },
  { to: "/gallery", label: "Gallery", icon: SquaresFour, end: false },
  { to: "/sync", label: "Sync", icon: DownloadSimple, end: false },
];

export function App() {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("theme") ?? "dark");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <div className="flex h-[100dvh] flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-line bg-canvas/80 px-4 backdrop-blur">
          <Link to="/gallery" aria-label="Open Gallery" title="Open Gallery" className="flex items-center gap-2 rounded-[var(--radius-control)] text-ink transition hover:text-accent">
            <BookmarkSimple size={18} weight="fill" className="text-accent" />
            <span className="text-sm font-semibold">Favorites Archive</span>
          </Link>
          <nav className="flex items-center gap-1">
            {TABS.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cx(
                    "inline-flex items-center gap-1.5 rounded-[var(--radius-control)] px-3 py-1.5 text-sm transition",
                    isActive ? "bg-elevated text-ink" : "text-ink-dim hover:text-ink",
                  )
                }
              >
                <Icon size={16} />
                <span className="sr-only sm:not-sr-only">{label}</span>
              </NavLink>
            ))}
            <button
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              aria-label="Toggle theme"
              className="ml-1 rounded-[var(--radius-control)] p-1.5 text-ink-dim transition hover:text-ink"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </nav>
        </header>

        <main className="min-h-0 flex-1">
          <Routes>
            <Route path="/" element={<Viewer />} />
            <Route path="/gallery" element={<Gallery />} />
            <Route path="/sync" element={<Dashboard />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

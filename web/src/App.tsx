import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Link } from "react-router-dom";
import { FilmReel, SquaresFour, MusicNotes, ChartBar, DownloadSimple, HardDrives, Archive, Sun, Moon, BookmarkSimple, Compass } from "@phosphor-icons/react";
import { Viewer } from "./routes/Viewer";
import { Gallery } from "./routes/Gallery";
import { Music } from "./routes/Music";
import { Stats } from "./routes/Stats";
import { Dashboard } from "./routes/Dashboard";
import { Storage } from "./routes/Storage";
import { Backups } from "./routes/Backups";
import { Discover } from "./routes/Discover";
import { cx } from "./components/ui";

const TABS = [
  { to: "/", label: "Feed", icon: FilmReel, end: true },
  { to: "/gallery", label: "Gallery", icon: SquaresFour, end: false },
  { to: "/music", label: "Music", icon: MusicNotes, end: false },
  { to: "/stats", label: "Stats", icon: ChartBar, end: false },
  { to: "/discover", label: "Discover", icon: Compass, end: false },
  { to: "/storage", label: "Storage", icon: HardDrives, end: false },
  { to: "/backups", label: "Backups", icon: Archive, end: false },
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
        <header className="flex h-14 shrink-0 items-center justify-between gap-1 border-b border-line bg-canvas/80 px-2 backdrop-blur sm:px-4">
          <Link to="/gallery" aria-label="Open Gallery" title="Open Gallery" className="flex shrink-0 items-center gap-2 rounded-[var(--radius-control)] text-ink transition hover:text-accent">
            <BookmarkSimple size={18} weight="fill" className="text-accent" />
            <span className="hidden text-sm font-semibold min-[420px]:inline">Favorites Archive</span>
          </Link>
          <nav className="flex min-w-0 items-center gap-0.5 overflow-x-auto sm:gap-1">
            {TABS.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cx(
                    "inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-control)] px-2 py-1.5 text-sm transition sm:px-3",
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
              className="ml-1 hidden shrink-0 rounded-[var(--radius-control)] p-1.5 text-ink-dim transition hover:text-ink min-[380px]:block"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </nav>
        </header>

        <main className="min-h-0 flex-1">
          <Routes>
            <Route path="/" element={<Viewer />} />
            <Route path="/gallery" element={<Gallery />} />
            <Route path="/music" element={<Music />} />
            <Route path="/stats" element={<Stats />} />
            <Route path="/discover" element={<Discover />} />
            <Route path="/storage" element={<Storage />} />
            <Route path="/backups" element={<Backups />} />
            <Route path="/sync" element={<Dashboard />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

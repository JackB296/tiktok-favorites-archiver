import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Link } from "react-router-dom";
import { FilmReel, SquaresFour, MusicNotes, ChartBar, DownloadSimple, HardDrives, Archive, Sun, Moon, BookmarkSimple, Compass, MagnifyingGlass, ClockCounterClockwise, Sparkle, Scissors, Star, WaveSine, Copy, Television } from "@phosphor-icons/react";
import { cx } from "./components/ui";

const Viewer = lazy(() => import("./routes/Viewer").then((module) => ({ default: module.Viewer })));
const Gallery = lazy(() => import("./routes/Gallery").then((module) => ({ default: module.Gallery })));
const Music = lazy(() => import("./routes/Music").then((module) => ({ default: module.Music })));
const Stats = lazy(() => import("./routes/Stats").then((module) => ({ default: module.Stats })));
const Dashboard = lazy(() => import("./routes/Dashboard").then((module) => ({ default: module.Dashboard })));
const Storage = lazy(() => import("./routes/Storage").then((module) => ({ default: module.Storage })));
const Backups = lazy(() => import("./routes/Backups").then((module) => ({ default: module.Backups })));
const Discover = lazy(() => import("./routes/Discover").then((module) => ({ default: module.Discover })));
const Lens = lazy(() => import("./routes/Lens").then((module) => ({ default: module.Lens })));
const History = lazy(() => import("./routes/History").then((module) => ({ default: module.History })));
const Memories = lazy(() => import("./routes/Memories").then((module) => ({ default: module.Memories })));
const Stories = lazy(() => import("./routes/Stories").then((module) => ({ default: module.Stories })));
const Curate = lazy(() => import("./routes/Curate").then((module) => ({ default: module.Curate })));
const Vibes = lazy(() => import("./routes/Vibes").then((module) => ({ default: module.Vibes })));
const Duplicates = lazy(() => import("./routes/Duplicates").then((module) => ({ default: module.Duplicates })));
const Channels = lazy(() => import("./routes/Channels").then((module) => ({ default: module.Channels })));

const TABS = [
  { to: "/", label: "Feed", icon: FilmReel, end: true },
  { to: "/gallery", label: "Gallery", icon: SquaresFour, end: false },
  { to: "/music", label: "Music", icon: MusicNotes, end: false },
  { to: "/stats", label: "Stats", icon: ChartBar, end: false },
  { to: "/discover", label: "Discover", icon: Compass, end: false },
  { to: "/lens", label: "Lens", icon: MagnifyingGlass, end: false },
  { to: "/history", label: "History", icon: ClockCounterClockwise, end: false },
  { to: "/memories", label: "Memories", icon: Sparkle, end: false },
  { to: "/stories", label: "Stories", icon: Scissors, end: false },
  { to: "/curate", label: "Curate", icon: Star, end: false },
  { to: "/vibes", label: "Vibes", icon: WaveSine, end: false },
  { to: "/duplicates", label: "Duplicates", icon: Copy, end: false },
  { to: "/channels", label: "Channels", icon: Television, end: false },
  { to: "/storage", label: "Storage", icon: HardDrives, end: false },
  { to: "/backups", label: "Backups", icon: Archive, end: false },
  { to: "/sync", label: "Sync", icon: DownloadSimple, end: false },
];

function RouteFallback() {
  return (
    <div className="h-full bg-canvas" role="status" aria-live="polite" aria-label="Loading page">
      <span className="sr-only">Loading page…</span>
    </div>
  );
}

export function App() {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("theme") ?? "dark");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <div className="flex h-[100dvh] flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-1 overflow-hidden border-b border-line bg-canvas/80 px-2 backdrop-blur sm:px-4">
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
                aria-label={label}
                title={label}
                className={({ isActive }) =>
                  cx(
                    "inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-control)] px-2 py-1.5 text-sm transition sm:px-3",
                    isActive ? "bg-elevated text-ink" : "text-ink-dim hover:text-ink",
                  )
                }
              >
                <Icon size={16} />
                <span className={cx("sr-only min-[1800px]:not-sr-only", (label === "Feed" || label === "Gallery") && "sm:not-sr-only")}>{label}</span>
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
          <Suspense fallback={<RouteFallback />}>
            <Routes>
              <Route path="/" element={<Viewer />} />
              <Route path="/gallery" element={<Gallery />} />
              <Route path="/music" element={<Music />} />
              <Route path="/stats" element={<Stats />} />
              <Route path="/discover" element={<Discover />} />
              <Route path="/lens" element={<Lens />} />
              <Route path="/history" element={<History />} />
              <Route path="/memories" element={<Memories />} />
              <Route path="/stories" element={<Stories />} />
              <Route path="/curate" element={<Curate />} />
              <Route path="/vibes" element={<Vibes />} />
              <Route path="/duplicates" element={<Duplicates />} />
              <Route path="/channels" element={<Channels />} />
              <Route path="/storage" element={<Storage />} />
              <Route path="/backups" element={<Backups />} />
              <Route path="/sync" element={<Dashboard />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </BrowserRouter>
  );
}

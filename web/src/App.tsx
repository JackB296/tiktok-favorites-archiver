import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, Link } from "react-router-dom";
import { FilmReel, SquaresFour, MusicNotes, ChartBar, DownloadSimple, HardDrives, Archive, Sun, Moon, BookmarkSimple, Compass, MagnifyingGlass, ClockCounterClockwise, Sparkle, Star, WaveSine, Copy, Television, CaretDown } from "@phosphor-icons/react";
import { cx } from "./components/ui";
import { navigationGroups, primaryNavigation } from "./lib/navigation";

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
const Curate = lazy(() => import("./routes/Curate").then((module) => ({ default: module.Curate })));
const Vibes = lazy(() => import("./routes/Vibes").then((module) => ({ default: module.Vibes })));
const Duplicates = lazy(() => import("./routes/Duplicates").then((module) => ({ default: module.Duplicates })));
const Channels = lazy(() => import("./routes/Channels").then((module) => ({ default: module.Channels })));

const ICONS = {
  Feed: FilmReel, Gallery: SquaresFour, Music: MusicNotes, Stats: ChartBar,
  Sync: DownloadSimple, Storage: HardDrives, Backups: Archive, Discover: Compass,
  Lens: MagnifyingGlass, History: ClockCounterClockwise, Memories: Sparkle,
  Curate: Star, Vibes: WaveSine, Duplicates: Copy, Channels: Television,
};

function NavigationLink({ to, label, compact = false }: { to: string; label: keyof typeof ICONS; compact?: boolean }) {
  const Icon = ICONS[label];
  return <NavLink
    to={to}
    end={to === "/"}
    className={({ isActive }) => cx(
      "inline-flex items-center gap-1.5 rounded-[var(--radius-control)] px-2.5 py-1.5 text-sm transition",
      isActive ? "bg-elevated text-ink" : "text-ink-dim hover:bg-elevated hover:text-ink",
    )}
  >
    <Icon size={16} aria-hidden />
    <span className={compact ? "sr-only" : ""}>{label}</span>
  </NavLink>;
}

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
        <a href="#app-main" className="sr-only z-[60] rounded-[var(--radius-control)] bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:absolute focus:left-3 focus:top-3">Skip to content</a>
        <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line bg-canvas/80 px-2 backdrop-blur sm:px-4">
          <Link to="/gallery" aria-label="Open Gallery" title="Open Gallery" className="flex shrink-0 items-center gap-2 rounded-[var(--radius-control)] text-ink transition hover:text-accent">
            <BookmarkSimple size={18} weight="fill" className="text-accent" />
            <span className="hidden text-sm font-semibold min-[700px]:inline">Favorites Archive</span>
          </Link>
          <nav aria-label="Primary navigation" className="flex min-w-0 items-center gap-1">
            {primaryNavigation.map((item) => item.to === "/gallery" || item.to === "/sync"
              ? <span key={item.to} className="hidden min-[700px]:inline-flex"><NavigationLink to={item.to} label={item.label} /></span>
              : <NavigationLink key={item.to} to={item.to} label={item.label} />)}
            <details className="group relative">
              <summary className="flex h-9 cursor-pointer list-none items-center gap-1 rounded-[var(--radius-control)] px-2 text-sm text-ink-dim hover:bg-elevated hover:text-ink">
                More <CaretDown size={14} aria-hidden className="transition group-open:rotate-180" />
              </summary>
              <div className="absolute right-0 top-11 z-50 grid w-72 gap-3 rounded-[var(--radius-media)] border border-line bg-surface p-3 shadow-2xl">
                {navigationGroups.map((group) => <section key={group.label} aria-label={`${group.label} tools`}>
                  <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">{group.label}</p>
                  <div className="grid grid-cols-2 gap-1">
                    {group.items.filter((item) => item.to !== "/").map((item) => <NavigationLink key={item.to} to={item.to} label={item.label} />)}
                  </div>
                </section>)}
              </div>
            </details>
            <button
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              aria-label="Toggle theme"
              className="ml-1 hidden shrink-0 rounded-[var(--radius-control)] p-1.5 text-ink-dim transition hover:text-ink min-[700px]:block"
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </nav>
        </header>

        <main id="app-main" className="min-h-0 flex-1" tabIndex={-1}>
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

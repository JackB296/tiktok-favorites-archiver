import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SpeakerSimpleHigh, SpeakerSimpleX, ArrowSquareOut, FilmReel, Shuffle, Keyboard } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { PostMedia } from "../components/PostMedia";
import { PlaybackSession, usePlayback } from "../components/playback";
import { EmptyState, Skeleton } from "../components/ui";

const KEEP_BEHIND = 5;
const PRELOAD_AHEAD = 2;

export function Viewer() {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<Item[] | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [randomMode, setRandomMode] = useState(false);
  const [randomizing, setRandomizing] = useState(false);
  const [randomPosition, setRandomPosition] = useState<number | null>(null);
  const [randomTotal, setRandomTotal] = useState(0);
  const resumeId = useRef<number | null>(Number(localStorage.getItem("last-watched-favorite")) || null);
  const containerRef = useRef<HTMLDivElement>(null);
  const randomQueue = useRef<number[]>([]);
  const randomOffset = useRef(0);
  const randomGeneration = useRef(0);
  const randomBatchGeneration = useRef<number | null>(null);
  const randomPositions = useRef(new Map<number, number>());
  const requestedItemId = Number(searchParams.get("item")) || null;

  useEffect(() => {
    let alive = true;
    const openLatest = () => api.itemPage({ limit: 50, order: "latest" }).then((page) => {
      if (!alive) return;
      const playable = page.items.filter((i) => i.video_url || i.images.length);
      setItems(playable);
      setNextCursor(page.next_cursor);
      if (playable[0]) setActiveId(playable[0].id);
    });

    if (requestedItemId != null) {
      api.itemWindow(requestedItemId)
        .then((page) => {
          if (!alive) return;
          const playable = page.items.filter((i) => i.video_url || i.images.length);
          if (!playable.some((item) => item.id === requestedItemId)) return openLatest();
          setItems(playable);
          setActiveId(requestedItemId);
          setNextCursor(page.items[page.items.length - 1]?.id ?? null);
        })
        .catch(() => openLatest().catch(() => alive && setItems([])));
    } else {
      openLatest().catch(() => alive && setItems([]));
    }

    return () => {
      alive = false;
    };
  }, [requestedItemId]);

  /*
   * Gallery hands off with ?item=<id>. The selected item becomes the first
   * visible Feed entry; the normal older-neighbor cursor then takes over.
   */
  useEffect(() => {
    if (requestedItemId == null || activeId !== requestedItemId) return;
    requestAnimationFrame(() => containerRef.current?.scrollTo({ top: 0 }));
  }, [activeId, requestedItemId]);

  const loadRandomBatch = useCallback(async (replace = false, generation = randomGeneration.current) => {
    if (generation !== randomGeneration.current || randomBatchGeneration.current === generation) return;
    const ids = randomQueue.current.slice(randomOffset.current, randomOffset.current + 50);
    if (!ids.length) return;
    randomOffset.current += ids.length;
    randomBatchGeneration.current = generation;
    setLoadingMore(true);
    try {
      const selected = await api.itemSelection(ids);
      if (generation !== randomGeneration.current) return;
      const playable = selected.filter((item) => item.video_url || item.images.length);
      if (replace) {
        setItems(playable);
        setActiveId(playable[0]?.id ?? null);
        requestAnimationFrame(() => containerRef.current?.scrollTo({ top: 0 }));
      } else if (playable.length) {
        setItems((current) => [...(current ?? []), ...playable]);
      }
    } finally {
      if (randomBatchGeneration.current === generation) randomBatchGeneration.current = null;
      if (generation === randomGeneration.current) setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    const root = containerRef.current;
    if (!root || !items?.length) return;
    const io = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (top) {
          const id = Number((top.target as HTMLElement).dataset.id);
          if (!Number.isNaN(id)) setActiveId(id);
        }
      },
      { root, threshold: 0.6 },
    );
    root.querySelectorAll("[data-id]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [items]);

  useEffect(() => {
    if (!items?.length || activeId == null || loadingMore) return;
    if (items.findIndex((item) => item.id === activeId) < items.length - 3) return;
    if (randomMode) {
      void loadRandomBatch();
      return;
    }
    if (nextCursor == null) return;
    setLoadingMore(true);
    api.itemPage({ limit: 50, cursor: nextCursor, order: "latest" })
      .then((page) => {
        setItems((current) => [...(current ?? []), ...page.items]);
        setNextCursor(page.next_cursor);
      })
      .finally(() => setLoadingMore(false));
  }, [activeId, items, loadRandomBatch, loadingMore, nextCursor, randomMode]);

  useEffect(() => {
    if (activeId == null) return;
    const activeIndex = items?.findIndex((item) => item.id === activeId) ?? -1;
    const removeCount = activeIndex - KEEP_BEHIND;
    if (removeCount <= 0) return;
    setItems((current) => current?.slice(removeCount) ?? null);
    requestAnimationFrame(() => {
      const root = containerRef.current;
      if (root) root.scrollTop -= removeCount * root.clientHeight;
    });
  }, [activeId, items]);

  useEffect(() => {
    if (activeId != null) localStorage.setItem("last-watched-favorite", String(activeId));
  }, [activeId]);

  useEffect(() => {
    setRandomPosition(randomMode && activeId != null ? randomPositions.current.get(activeId) ?? null : null);
  }, [activeId, randomMode]);

  async function goToLastWatched() {
    if (resumeId.current == null) return;
    const page = await api.itemWindow(resumeId.current).catch(() => null);
    if (!page?.items.length) return;
    randomGeneration.current += 1;
    setRandomMode(false);
    setRandomTotal(0);
    setItems(page.items);
    setActiveId(resumeId.current);
    setNextCursor(page.items[page.items.length - 1]?.id ?? null);
    requestAnimationFrame(() => containerRef.current?.scrollTo({ top: 0 }));
  }

  async function startRandom() {
    if (randomizing) return;
    const generation = randomGeneration.current + 1;
    randomGeneration.current = generation;
    setRandomizing(true);
    try {
      const ids = await api.itemIds();
      if (generation !== randomGeneration.current) return;
      if (!ids.length) return;
      for (let i = ids.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [ids[i], ids[j]] = [ids[j], ids[i]];
      }
      randomQueue.current = ids;
      randomPositions.current = new Map(ids.map((id, index) => [id, index]));
      randomOffset.current = 0;
      setRandomMode(true);
      setRandomTotal(ids.length);
      setNextCursor(null);
      await loadRandomBatch(true, generation);
    } catch {
      // Keep the current feed usable if randomization cannot be loaded.
    } finally {
      setRandomizing(false);
    }
  }

  async function returnToOrderedFeed() {
    randomGeneration.current += 1;
    setRandomMode(false);
    setRandomPosition(null);
    setRandomTotal(0);
    const page = await api.itemPage({ limit: 50, order: "latest" }).catch(() => null);
    if (!page) return;
    const playable = page.items.filter((item) => item.video_url || item.images.length);
    setItems(playable);
    setNextCursor(page.next_cursor);
    setActiveId(playable[0]?.id ?? null);
    requestAnimationFrame(() => containerRef.current?.scrollTo({ top: 0 }));
  }

  if (!items) {
    return (
      <div className="mx-auto max-w-md p-4">
        <Skeleton className="h-[82dvh] w-full !rounded-[var(--radius-media)]" />
      </div>
    );
  }
  if (!items.length) {
    return (
      <EmptyState
        icon={<FilmReel size={40} />}
        title="Nothing to watch yet"
        hint="Import your TikTok export and run a sync from the Sync tab, and your favorites show up here."
      />
    );
  }

  return (
    <PlaybackSession initiallyMuted>
      <ViewerFeed items={items} activeId={activeId} containerRef={containerRef} onActiveChange={setActiveId} onGoToLastWatched={resumeId.current ? goToLastWatched : undefined} onRandom={startRandom} randomizing={randomizing} randomMode={randomMode} randomPosition={randomPosition} randomTotal={randomTotal} onOrdered={returnToOrderedFeed} />
    </PlaybackSession>
  );
}

function ViewerFeed({ items, activeId, containerRef, onActiveChange, onGoToLastWatched, onRandom, randomizing, randomMode, randomPosition, randomTotal, onOrdered }: { items: Item[]; activeId: number | null; containerRef: React.RefObject<HTMLDivElement>; onActiveChange: (id: number) => void; onGoToLastWatched?: () => void; onRandom: () => void; randomizing: boolean; randomMode: boolean; randomPosition: number | null; randomTotal: number; onOrdered: () => void }) {
  const { muted, toggleMuted, paused, togglePaused, setPaused } = usePlayback();
  const Speaker = muted ? SpeakerSimpleX : SpeakerSimpleHigh;
  const activeIndex = items.findIndex((item) => item.id === activeId);
  const [showShortcuts, setShowShortcuts] = useState(false);

  useEffect(() => {
    setPaused(false);
  }, [activeId, setPaused]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, button, a, [contenteditable='true']")) return;
      if (event.key === " " || event.code === "Space") {
        if (!event.repeat) togglePaused();
        event.preventDefault();
        return;
      }
      if (event.key.toLowerCase() === "m") {
        if (!event.repeat) toggleMuted();
        event.preventDefault();
        return;
      }
      const delta = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 0;
      if (!delta) return;
      const nextIndex = Math.max(0, Math.min(items.length - 1, (activeIndex < 0 ? 0 : activeIndex) + delta));
      if (nextIndex === activeIndex) return;
      event.preventDefault();
      const next = items[nextIndex];
      onActiveChange(next.id);
      containerRef.current?.querySelector<HTMLElement>(`[data-id="${next.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeIndex, containerRef, items, onActiveChange, toggleMuted, togglePaused]);

  return (
    <div ref={containerRef} className="h-full snap-y snap-mandatory overflow-y-scroll bg-black">
      <p className="sr-only" aria-live="polite">{paused ? "Paused" : "Playing"}</p>
      {onGoToLastWatched && <button onClick={onGoToLastWatched} className="absolute left-4 top-4 z-10 rounded bg-black/40 px-3 py-2 text-xs text-white backdrop-blur-sm">Go to last watched</button>}
      <button onClick={onRandom} disabled={randomizing} aria-label="Start a fresh random order" className="absolute left-4 top-14 z-10 rounded bg-black/40 p-2 text-white backdrop-blur-sm disabled:opacity-50"><Shuffle size={18} /></button>
      <button onClick={() => setShowShortcuts((value) => !value)} aria-label="Show keyboard shortcuts" aria-expanded={showShortcuts} className="absolute left-14 top-14 z-10 rounded bg-black/40 p-2 text-white backdrop-blur-sm"><Keyboard size={18} /></button>
      {randomMode && <div className="absolute left-4 top-24 z-10 flex items-center gap-2 rounded bg-black/55 px-2.5 py-1.5 text-xs text-white backdrop-blur-sm">Random · {randomPosition == null ? "…" : randomPosition + 1} / {randomTotal}<button onClick={onOrdered} className="text-white/70 underline underline-offset-2 hover:text-white">Ordered feed</button></div>}
      {showShortcuts && <div className="absolute left-4 top-36 z-10 rounded bg-black/65 px-3 py-2 text-xs leading-5 text-white backdrop-blur-sm">↑ ↓ / ← →: previous or next<br />Space: play or pause<br />M: mute or unmute</div>}
      {items.map((item, index) => (
        <section
          key={item.id}
          data-id={item.id}
          className="relative flex h-full snap-start items-center justify-center"
        >
          <PostMedia item={item} active={item.id === activeId} preload={index > activeIndex && index <= activeIndex + PRELOAD_AHEAD} />

          <button
            onClick={toggleMuted}
            aria-label={muted ? "Unmute" : "Mute"}
            className="absolute right-4 top-4 rounded-full bg-black/40 p-2.5 text-white backdrop-blur-sm transition hover:bg-black/60 active:translate-y-px"
          >
            <Speaker size={20} weight="fill" />
          </button>

          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-5 pt-20">
            <div className="mx-auto max-w-md">
              {item.author && <p className="text-sm font-semibold text-white">{item.author}</p>}
              {item.caption && <p className="mt-1 line-clamp-2 text-sm text-white/80">{item.caption}</p>}
              <a
                href={item.link}
                target="_blank"
                rel="noreferrer"
                className="pointer-events-auto mt-2 inline-flex items-center gap-1.5 text-xs text-white/60 hover:text-white"
              >
                <span className="tabular">#{item.id}</span>
                <ArrowSquareOut size={13} />
                open on TikTok
              </a>
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}

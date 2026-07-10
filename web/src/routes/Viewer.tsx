import { useCallback, useEffect, useRef, useState } from "react";
import { SpeakerSimpleHigh, SpeakerSimpleX, ArrowSquareOut, FilmReel, Shuffle } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { PostMedia } from "../components/PostMedia";
import { PlaybackSession, usePlayback } from "../components/playback";
import { EmptyState, Skeleton } from "../components/ui";

export function Viewer() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [randomMode, setRandomMode] = useState(false);
  const [randomizing, setRandomizing] = useState(false);
  const resumeId = useRef<number | null>(Number(localStorage.getItem("last-watched-favorite")) || null);
  const containerRef = useRef<HTMLDivElement>(null);
  const randomQueue = useRef<number[]>([]);
  const randomOffset = useRef(0);
  const randomGeneration = useRef(0);
  const randomBatchGeneration = useRef<number | null>(null);

  useEffect(() => {
    api
      .itemPage({ limit: 50, order: "latest" })
      .then((page) => {
        const playable = page.items.filter((i) => i.video_url || i.images.length);
        setItems(playable);
        setNextCursor(page.next_cursor);
        if (playable[0]) setActiveId(playable[0].id);
      })
      .catch(() => setItems([]));
  }, []);

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
    if (activeId != null) localStorage.setItem("last-watched-favorite", String(activeId));
  }, [activeId]);

  async function goToLastWatched() {
    if (resumeId.current == null) return;
    const page = await api.itemWindow(resumeId.current).catch(() => null);
    if (!page?.items.length) return;
    randomGeneration.current += 1;
    setRandomMode(false);
    setItems(page.items);
    setActiveId(resumeId.current);
    setNextCursor(page.items[page.items.length - 1]?.id ?? null);
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
      randomOffset.current = 0;
      setRandomMode(true);
      setNextCursor(null);
      await loadRandomBatch(true, generation);
    } catch {
      // Keep the current feed usable if randomization cannot be loaded.
    } finally {
      setRandomizing(false);
    }
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
      <ViewerFeed items={items} activeId={activeId} containerRef={containerRef} onGoToLastWatched={resumeId.current ? goToLastWatched : undefined} onRandom={startRandom} randomizing={randomizing} />
    </PlaybackSession>
  );
}

function ViewerFeed({ items, activeId, containerRef, onGoToLastWatched, onRandom, randomizing }: { items: Item[]; activeId: number | null; containerRef: React.RefObject<HTMLDivElement>; onGoToLastWatched?: () => void; onRandom: () => void; randomizing: boolean }) {
  const { muted, toggleMuted } = usePlayback();
  const Speaker = muted ? SpeakerSimpleX : SpeakerSimpleHigh;

  return (
    <div ref={containerRef} className="h-full snap-y snap-mandatory overflow-y-scroll bg-black">
      {onGoToLastWatched && <button onClick={onGoToLastWatched} className="absolute left-4 top-4 z-10 rounded bg-black/40 px-3 py-2 text-xs text-white backdrop-blur-sm">Go to last watched</button>}
      <button onClick={onRandom} disabled={randomizing} aria-label="Start a new random order" className="absolute left-4 top-14 z-10 rounded bg-black/40 p-2 text-white backdrop-blur-sm disabled:opacity-50"><Shuffle size={18} /></button>
      {items.map((item) => (
        <section
          key={item.id}
          data-id={item.id}
          className="relative flex h-full snap-start items-center justify-center"
        >
          <PostMedia item={item} active={item.id === activeId} />

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

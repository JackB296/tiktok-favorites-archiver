import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SpeakerSimpleHigh, SpeakerSimpleX, ArrowSquareOut, FilmReel, Shuffle, Keyboard, CornersOut, ClockCounterClockwise } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { PostMedia } from "../components/PostMedia";
import { PlaybackSession, usePlayback } from "../components/playback";
import { EmptyState, Skeleton } from "../components/ui";
import { viewerShortcut } from "../lib/viewerShortcuts";
import { isFeedItem } from "../lib/feedItems";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import { activeFeedIndex, feedTrimPlan, nextWheelTargetIndex, shouldCommitWheelTarget } from "../lib/viewerFeed.js";
import { formatAutoGain } from "../lib/playbackVolume.js";
import { captionParts, cleanMetadataText, hashtagGalleryUrl } from "../lib/captionPresentation.js";

const KEEP_BEHIND = 5;
const PRELOAD_AHEAD = 4;

export function Viewer() {
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState<Item[] | null>(null);
  const initialLoadingPhase = useDelayedLoading(items === null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [transitionTargetId, setTransitionTargetId] = useState<number | null>(null);
  const [randomMode, setRandomMode] = useState(false);
  const [randomizing, setRandomizing] = useState(false);
  const [randomPosition, setRandomPosition] = useState<number | null>(null);
  const [randomTotal, setRandomTotal] = useState(0);
  const [queueReadyTotal, setQueueReadyTotal] = useState(0);
  const resumeId = useRef<number | null>(Number(localStorage.getItem("last-watched-favorite")) || null);
  const containerRef = useRef<HTMLDivElement>(null);
  const randomQueue = useRef<number[]>([]);
  const randomOffset = useRef(0);
  const randomGeneration = useRef(0);
  const randomBatchGeneration = useRef<number | null>(null);
  const randomPositions = useRef(new Map<number, number>());
  const pendingTrim = useRef<{ removeCount: number; restoredScrollTop: number } | null>(null);
  const pendingWheelTargetId = useRef<number | null>(null);
  const wheelGestureReady = useRef(true);
  const wheelIdleTimer = useRef<number | null>(null);
  const wheelSettleTimer = useRef<number | null>(null);
  const requestedItemId = Number(searchParams.get("item")) || null;
  const requestedQueueIds = Array.from(new Set((searchParams.get("queue") ?? "").split(",").map(Number).filter((id) => Number.isSafeInteger(id) && id > 0))).slice(0, 100);
  const requestedQueueKey = requestedQueueIds.join(",");
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;

  useEffect(() => {
    let alive = true;
    const openLatest = () => api.itemPage({ limit: 50, order: "latest", feed: true }).then((page) => {
      if (!alive) return;
      const playable = page.items.filter(isFeedItem);
      setItems(playable);
      setQueueReadyTotal(0);
      setNextCursor(page.next_cursor);
      if (playable[0]) setActiveId(playable[0].id);
    });

    if (requestedQueueIds.length) {
      api.itemSelection(requestedQueueIds)
        .then((selected) => {
          if (!alive) return;
          const playable = selected.filter(isFeedItem);
          setItems(playable);
          setQueueReadyTotal(playable.length);
          setActiveId(playable[0]?.id ?? null);
          setNextCursor(null); // a curated queue ends at its final selected item
          setRandomMode(false);
        })
        .catch(() => alive && setItems([]));
    } else if (requestedItemId != null) {
      setQueueReadyTotal(0);
      api.itemWindow(requestedItemId)
        .then((page) => {
          if (!alive) return;
          const playable = page.items.filter(isFeedItem);
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
  }, [requestedItemId, requestedQueueKey]);

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
      const playable = selected.filter(isFeedItem);
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
    let frame = 0;
    const updateActive = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const pendingId = pendingWheelTargetId.current;
        if (pendingId != null) {
          const targetIndex = items.findIndex((item) => item.id === pendingId);
          if (targetIndex >= 0 && shouldCommitWheelTarget(root.scrollTop, root.clientHeight, targetIndex)) {
            if (wheelSettleTimer.current != null) window.clearTimeout(wheelSettleTimer.current);
            wheelSettleTimer.current = null;
            pendingWheelTargetId.current = null;
            setTransitionTargetId(null);
            setActiveId(pendingId);
          }
          return;
        }
        const next = items[activeFeedIndex(root.scrollTop, root.clientHeight, items.length)];
        if (next) setActiveId((current) => current === next.id ? current : next.id);
      });
    };
    root.addEventListener("scroll", updateActive, { passive: true });
    updateActive();
    return () => {
      window.cancelAnimationFrame(frame);
      root.removeEventListener("scroll", updateActive);
    };
  }, [items]);

  useEffect(() => {
    const root = containerRef.current;
    if (!root || !items?.length) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX) || Math.abs(event.deltaY) < 2) return;
      event.preventDefault();
      if (wheelIdleTimer.current != null) window.clearTimeout(wheelIdleTimer.current);
      wheelIdleTimer.current = window.setTimeout(() => { wheelGestureReady.current = true; }, 100);
      if (!wheelGestureReady.current) return;
      wheelGestureReady.current = false;

      const activeIndex = items.findIndex((item) => item.id === activeIdRef.current);
      const pendingIndex = items.findIndex((item) => item.id === pendingWheelTargetId.current);
      const nextIndex = nextWheelTargetIndex(activeIndex, pendingIndex, event.deltaY, items.length);
      const next = items[nextIndex];
      if (!next || nextIndex === pendingIndex || (pendingIndex < 0 && nextIndex === activeIndex)) return;
      pendingWheelTargetId.current = next.id;
      setTransitionTargetId(next.id);
      if (wheelSettleTimer.current != null) window.clearTimeout(wheelSettleTimer.current);
      wheelSettleTimer.current = window.setTimeout(() => {
        root.scrollTo({ top: nextIndex * root.clientHeight, behavior: "auto" });
        pendingWheelTargetId.current = null;
        setTransitionTargetId(null);
        setActiveId(next.id);
        wheelSettleTimer.current = null;
      }, 900);
      root.scrollTo({ top: nextIndex * root.clientHeight, behavior: "smooth" });
    };
    root.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      root.removeEventListener("wheel", onWheel);
    };
  }, [items]);

  useEffect(() => () => {
    if (wheelIdleTimer.current != null) window.clearTimeout(wheelIdleTimer.current);
    if (wheelSettleTimer.current != null) window.clearTimeout(wheelSettleTimer.current);
  }, []);

  useEffect(() => {
    if (!items?.length || activeId == null || loadingMore) return;
    if (items.findIndex((item) => item.id === activeId) < items.length - 3) return;
    if (randomMode) {
      void loadRandomBatch();
      return;
    }
    if (nextCursor == null) return;
    setLoadingMore(true);
    api.itemPage({ limit: 50, cursor: nextCursor, order: "latest", feed: true })
      .then((page) => {
        setItems((current) => [...(current ?? []), ...page.items.filter(isFeedItem)]);
        setNextCursor(page.next_cursor);
      })
      .finally(() => setLoadingMore(false));
  }, [activeId, items, loadRandomBatch, loadingMore, nextCursor, randomMode]);

  useEffect(() => {
    const root = containerRef.current;
    if (activeId == null || !root) return;
    const activeIndex = items?.findIndex((item) => item.id === activeId) ?? -1;
    const plan = feedTrimPlan(activeIndex, root.scrollTop, root.clientHeight, KEEP_BEHIND);
    if (plan.removeCount <= 0) return;
    pendingTrim.current = plan;
    setItems((current) => current?.slice(plan.removeCount) ?? null);
  }, [activeId, items]);

  useLayoutEffect(() => {
    const plan = pendingTrim.current;
    const root = containerRef.current;
    if (!plan || !root) return;
    root.scrollTop = plan.restoredScrollTop;
    pendingTrim.current = null;
  }, [items]);

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
    setItems(page.items.filter(isFeedItem));
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
    const page = await api.itemPage({ limit: 50, order: "latest", feed: true }).catch(() => null);
    if (!page) return;
    const playable = page.items.filter(isFeedItem);
    setItems(playable);
    setNextCursor(page.next_cursor);
    setActiveId(playable[0]?.id ?? null);
    requestAnimationFrame(() => containerRef.current?.scrollTo({ top: 0 }));
  }

  if (!items) {
    if (initialLoadingPhase === "quiet") return <div className="h-full bg-black" aria-busy="true" aria-label="Loading Feed" />;
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
    <PlaybackSession initiallyMuted={false}>
      <ViewerFeed items={items} activeId={activeId} transitionTargetId={transitionTargetId} containerRef={containerRef} onActiveChange={setActiveId} onGoToLastWatched={resumeId.current ? goToLastWatched : undefined} onRandom={startRandom} randomizing={randomizing} randomMode={randomMode} randomPosition={randomPosition} randomTotal={randomTotal} queueTotal={requestedQueueIds.length} queueReadyTotal={queueReadyTotal} onOrdered={returnToOrderedFeed} />
    </PlaybackSession>
  );
}

function ViewerFeed({ items, activeId, transitionTargetId, containerRef, onActiveChange, onGoToLastWatched, onRandom, randomizing, randomMode, randomPosition, randomTotal, queueTotal, queueReadyTotal, onOrdered }: { items: Item[]; activeId: number | null; transitionTargetId: number | null; containerRef: React.RefObject<HTMLDivElement>; onActiveChange: (id: number) => void; onGoToLastWatched?: () => void; onRandom: () => void; randomizing: boolean; randomMode: boolean; randomPosition: number | null; randomTotal: number; queueTotal: number; queueReadyTotal: number; onOrdered: () => void }) {
  const { muted, toggleMuted, volume, setVolume, autoLevel, toggleAutoLevel, autoGain, setAutoGain, paused, togglePaused, setPaused } = usePlayback();
  const Speaker = muted ? SpeakerSimpleX : SpeakerSimpleHigh;
  const activeIndex = items.findIndex((item) => item.id === activeId);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);

  const toggleFullscreen = useCallback(async () => {
    const target = containerRef.current;
    if (!target) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await target.requestFullscreen();
    } catch {
      // Fullscreen can be denied by browser policy; playback still works normally.
    }
  }, [containerRef]);

  useEffect(() => {
    const updateFullscreen = () => setFullscreen(document.fullscreenElement === containerRef.current);
    document.addEventListener("fullscreenchange", updateFullscreen);
    updateFullscreen();
    return () => document.removeEventListener("fullscreenchange", updateFullscreen);
  }, [containerRef]);

  useEffect(() => {
    setPaused(false);
    setAutoGain(1);
  }, [activeId, setAutoGain, setPaused]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const shortcut = viewerShortcut({ key: event.key, code: event.code, repeat: event.repeat, editing: Boolean(target?.closest("input, textarea, select, button, a, [contenteditable='true']")) });
      if (!shortcut) return;
      if (shortcut === "pause") { event.preventDefault(); togglePaused(); return; }
      if (shortcut === "mute") { event.preventDefault(); toggleMuted(); return; }
      if (shortcut === "fullscreen") { event.preventDefault(); void toggleFullscreen(); return; }
      const delta = shortcut === "next" ? 1 : -1;
      const nextIndex = Math.max(0, Math.min(items.length - 1, (activeIndex < 0 ? 0 : activeIndex) + delta));
      if (nextIndex === activeIndex) return;
      event.preventDefault();
      const next = items[nextIndex];
      onActiveChange(next.id);
      containerRef.current?.querySelector<HTMLElement>(`[data-id="${next.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeIndex, containerRef, items, onActiveChange, toggleFullscreen, toggleMuted, togglePaused]);

  return (
    <div ref={containerRef} className="relative h-full snap-y snap-mandatory overflow-y-scroll bg-black">
      <p className="sr-only" aria-live="polite">{paused ? "Paused" : "Playing"}</p>
      <div className="absolute left-3 top-3 z-20 flex items-center gap-1 rounded-xl border border-white/10 bg-black/55 p-1 text-white shadow-lg shadow-black/25 backdrop-blur-md">
        {onGoToLastWatched && <><button onClick={onGoToLastWatched} aria-label="Go to last watched" title="Return to the last favorite you watched" className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition hover:bg-white/15 active:translate-y-px"><ClockCounterClockwise size={16} /><span>Last watched</span></button><span aria-hidden="true" className="mx-0.5 h-5 w-px bg-white/15" /></>}
        <button onClick={onRandom} disabled={randomizing} aria-label="Start a fresh random order" title="Shuffle the archive" className="rounded-lg p-2 transition hover:bg-white/15 disabled:opacity-50"><Shuffle size={17} /></button>
        <button onClick={() => setShowShortcuts((value) => !value)} aria-label="Show keyboard shortcuts" aria-expanded={showShortcuts} title="Keyboard shortcuts" className="rounded-lg p-2 transition hover:bg-white/15"><Keyboard size={17} /></button>
        <button onClick={() => void toggleFullscreen()} aria-label={fullscreen ? "Exit fullscreen" : "Enter fullscreen"} aria-pressed={fullscreen} title={fullscreen ? "Exit fullscreen" : "Enter fullscreen"} className="rounded-lg p-2 transition hover:bg-white/15"><CornersOut size={17} /></button>
      </div>
      {randomMode && <div className="absolute left-3 top-16 z-20 flex items-center gap-2 rounded-lg border border-white/10 bg-black/55 px-2.5 py-1.5 text-xs text-white shadow-lg backdrop-blur-md">Random · {randomPosition == null ? "…" : randomPosition + 1} / {randomTotal}<button onClick={onOrdered} className="text-white/70 underline underline-offset-2 hover:text-white">Ordered feed</button></div>}
      {!randomMode && queueTotal > 0 && <div className="absolute left-3 top-16 z-20 rounded-lg border border-white/10 bg-black/55 px-2.5 py-1.5 text-xs text-white shadow-lg backdrop-blur-md">Gallery queue · {queueReadyTotal} ready of {queueTotal} selected</div>}
      {showShortcuts && <div className={`absolute left-3 z-20 rounded-xl border border-white/10 bg-black/70 px-3 py-2 text-xs leading-5 text-white shadow-xl backdrop-blur-md ${randomMode || queueTotal > 0 ? "top-28" : "top-16"}`}>↑ ↓ / ← →: previous or next<br />Space or video click: play or pause<br />M: mute or unmute<br />F: enter or exit fullscreen</div>}
      {items.map((item, index) => (
        <section
          key={item.id}
          data-id={item.id}
          className="relative flex h-full snap-start items-center justify-center"
        >
          <PostMedia item={item} active={item.id === activeId} transitioning={item.id === transitionTargetId} preload={(index > activeIndex && index <= activeIndex + PRELOAD_AHEAD) || item.id === transitionTargetId} />

          <div className="absolute right-4 top-4 flex items-center gap-2 rounded-full bg-black/45 p-1.5 text-white backdrop-blur-sm">
            <button
              onClick={toggleMuted}
              aria-label={muted ? "Unmute" : "Mute"}
              className="rounded-full p-1.5 transition hover:bg-white/15 active:translate-y-px"
            >
              <Speaker size={20} weight="fill" />
            </button>
            <label className="flex items-center gap-2 text-[10px] text-white/75">
              <span className="sr-only">Playback volume</span>
              <input
                aria-label="Playback volume"
                type="range"
                min="0"
                max="100"
                value={Math.round(volume * 100)}
                onChange={(event) => setVolume(Number(event.target.value) / 100)}
                className="h-1 w-20 cursor-pointer accent-white"
              />
              <span className="tabular w-7 text-right">{Math.round(volume * 100)}%</span>
            </label>
            <button
              onClick={toggleAutoLevel}
              aria-label={autoLevel ? "Disable automatic loudness leveling" : "Enable automatic loudness leveling"}
              aria-pressed={autoLevel}
              title="Automatically balances quiet and loud videos"
              className={`min-w-[72px] rounded-full px-2 py-1 text-[10px] font-semibold tabular-nums transition ${autoLevel ? "bg-white text-black" : "text-white/70 hover:bg-white/15"}`}
            >
              {autoLevel ? formatAutoGain(autoGain) : "Auto off"}
            </button>
          </div>

          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 via-black/45 to-transparent px-4 pb-4 pt-24 sm:px-6 sm:pb-6">
            <div className="mx-auto max-w-xl">
              {(cleanMetadataText(item.author) || cleanMetadataText(item.caption)) && <div className="rounded-2xl border border-white/10 bg-black/45 p-3.5 text-white shadow-xl shadow-black/20 backdrop-blur-md">
                {cleanMetadataText(item.author) && <div className="mb-2 flex items-center gap-2"><span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-white/55">Creator</span><span className="truncate text-sm font-semibold text-white">{cleanMetadataText(item.author)}</span></div>}
                {cleanMetadataText(item.caption) && <CaptionDescription caption={cleanMetadataText(item.caption)} />}
              </div>}
              <div className="mt-2 flex items-center gap-2 px-1 text-xs text-white/55">
                <span className="tabular">#{item.id}</span>
                {/^https?:\/\//i.test(item.link) && <a href={item.link} target="_blank" rel="noreferrer" className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full px-2 py-1 transition hover:bg-white/10 hover:text-white"><ArrowSquareOut size={13} />Open on TikTok</a>}
              </div>
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}

function CaptionDescription({ caption }: { caption: string }) {
  return <p className="line-clamp-3 whitespace-pre-wrap break-words text-[13px] leading-5 text-white/80 sm:text-sm">
    {captionParts(caption).map((part, index) => part.hashtag ? (
      <Link key={`${part.text}-${index}`} to={hashtagGalleryUrl(part.hashtag)} title={`Show all favorites tagged ${part.hashtag}`} className="pointer-events-auto rounded px-0.5 font-semibold text-white underline decoration-white/35 underline-offset-2 transition hover:bg-white/15 hover:decoration-white">{part.text}</Link>
    ) : <span key={`${part.text}-${index}`}>{part.text}</span>)}
  </p>;
}

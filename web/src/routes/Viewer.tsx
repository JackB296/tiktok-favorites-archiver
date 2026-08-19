import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SpeakerSimpleHigh, SpeakerSimpleX, SpeakerSlash, ArrowLeft, ArrowDown, FilmReel, Shuffle, Keyboard, CornersOut, ClockCounterClockwise, GearSix, MusicNotes, ChatCircle, CaretRight } from "@phosphor-icons/react";
import type { Item } from "../lib/types";
import { PostMedia } from "../components/PostMedia";
import { PlaybackSession, usePlayback } from "../components/playback";
import { Button, EmptyState, Skeleton, cx } from "../components/ui";
import { viewerShortcut } from "../lib/viewerShortcuts";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import { nextAutoAdvanceItem, playbackItemId, shouldPreloadItem } from "../lib/viewerFeed.js";
import type { FeedSource } from "../lib/feedWindow";
import { channelFeedSource, filteredFeedSource, latestFeedSource, queueFeedSource, randomFeedSource, resumeFeedSource } from "../lib/feedSources";
import { useFeedWindow } from "../lib/useFeedWindow";
import type { FeedWindow } from "../lib/useFeedWindow";
import { formatAutoGain } from "../lib/playbackVolume.js";
import { audioStatus } from "../lib/format";
import { MediaSettingsDialog } from "../components/MediaSettingsDialog";
import { SongIdentifyDialog } from "../components/SongIdentifyDialog";
import { CommentsDialog } from "../components/CommentsDialog";
import { PostDetailsPanel } from "../components/PostDetailsPanel";
import { PANEL_WIDTH } from "../lib/panelLayout.js";
import { readLensStartTime } from "../lib/lensPresentation.js";
import { api } from "../lib/api";
import { channelAdvanceAction, channelMediaKey } from "../lib/channelPlayback";

export function Viewer() {
  const [searchParams] = useSearchParams();
  const [reloadNonce, setReloadNonce] = useState(0);
  const resumeId = useRef<number | null>(Number(localStorage.getItem("last-watched-favorite")) || null);
  const containerRef = useRef<HTMLDivElement>(null);
  const overrideNonce = useRef(0);
  const lastRecordedPlay = useRef<number | null>(null);
  const requestedItemId = Number(searchParams.get("item")) || null;
  const requestedStartS = readLensStartTime(searchParams.get("start_s"));
  const requestedQueueIds = Array.from(new Set((searchParams.get("queue") ?? "").split(",").map(Number).filter((id) => Number.isSafeInteger(id) && id > 0))).slice(0, 100);
  const requestedQueueKey = requestedQueueIds.join(",");
  const requestedChannelId = Number(searchParams.get("channel")) || null;
  const filterParams = new URLSearchParams(searchParams);
  filterParams.delete("item");
  filterParams.delete("queue");
  filterParams.delete("from");
  filterParams.delete("start_s");
  filterParams.delete("channel");
  const filterKey = filterParams.toString();
  const filterActive = filterKey.length > 0;
  const backFrom = searchParams.has("from") ? (searchParams.get("from") ?? "") : null;
  const backHref = backFrom == null ? null : backFrom ? `/gallery?${backFrom}` : "/gallery";

  // One URL identity → one source. Imperative overrides (shuffle, resume,
  // ordered) are scoped to the URL they were started from, so any URL change
  // drops them and the URL-derived source takes over again.
  const urlKey = `${requestedItemId ?? ""}|${requestedStartS ?? ""}|${requestedQueueKey}|${requestedChannelId ?? ""}|${filterKey}|${reloadNonce}`;
  const urlSource = useMemo<FeedSource<Item>>(() => {
    if (requestedChannelId != null) return channelFeedSource(requestedChannelId, `channel:${urlKey}`);
    if (requestedQueueIds.length) return queueFeedSource(requestedQueueIds, `queue:${urlKey}`);
    if (requestedItemId != null) return filteredFeedSource(filterKey, requestedItemId, `filtered:${urlKey}`);
    return latestFeedSource(`latest:${urlKey}`);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlKey]);
  const [override, setOverride] = useState<{ source: FeedSource<Item>; urlKey: string } | null>(null);
  const feed = useFeedWindow(override?.urlKey === urlKey ? override.source : urlSource, containerRef);
  // Navigating away discards the override for good — otherwise browser-Back to
  // its urlKey would resurrect a stale shuffle instead of the URL's feed. An
  // override set for the current urlKey survives (the functional update keeps
  // the same reference, and this effect only runs when urlKey changes).
  useEffect(() => {
    setOverride((current) => (current && current.urlKey !== urlKey ? null : current));
  }, [urlKey]);
  const initialLoadingPhase = useDelayedLoading(feed.items === null);
  const randomizing = feed.switchingTo === "random";

  useEffect(() => {
    if (feed.activeId == null) return;
    localStorage.setItem("last-watched-favorite", String(feed.activeId));
    if (lastRecordedPlay.current === feed.activeId) return;
    lastRecordedPlay.current = feed.activeId;
    void api.recordPlayed(feed.activeId).catch(() => {});
  }, [feed.activeId]);

  function switchTo(make: (nonce: string) => FeedSource<Item>) {
    overrideNonce.current += 1;
    setOverride({ source: make(String(overrideNonce.current)), urlKey });
  }

  function startRandom() {
    if (randomizing) return;
    switchTo((nonce) => randomFeedSource(`random:${nonce}`));
  }

  function goToLastWatched() {
    const itemId = resumeId.current;
    if (itemId == null) return;
    switchTo((nonce) => resumeFeedSource(itemId, `resume:${nonce}`));
  }

  function returnToOrderedFeed() {
    switchTo((nonce) => latestFeedSource(`ordered:${nonce}`, { scrollToTop: true, keepOnError: true }));
  }

  if (!feed.items) {
    if (initialLoadingPhase === "quiet") return <div className="h-full bg-black" aria-busy="true" aria-label="Loading Feed" />;
    return (
      <div className="mx-auto max-w-md p-4">
        <Skeleton className="h-[82dvh] w-full !rounded-[var(--radius-media)]" />
      </div>
    );
  }
  if (feed.error !== null) {
    return (
      <EmptyState
        icon={<FilmReel size={40} />}
        title="Couldn't load the Feed"
        hint={<>{feed.error}<br /><Button size="sm" className="mt-3" onClick={() => setReloadNonce((n) => n + 1)}>Try again</Button></>}
      />
    );
  }
  if (!feed.items.length) {
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
      <ViewerFeed feed={feed} containerRef={containerRef} onGoToLastWatched={resumeId.current ? goToLastWatched : undefined} onRandom={startRandom} onOrdered={returnToOrderedFeed} onChannelRestart={() => setReloadNonce((nonce) => nonce + 1)} channelPlaybackGeneration={reloadNonce} filterActive={filterActive} backHref={backHref} queueTotal={requestedQueueIds.length} requestedItemId={requestedItemId} requestedStartS={requestedStartS} />
    </PlaybackSession>
  );
}

function ViewerFeed({ feed, containerRef, onGoToLastWatched, onRandom, onOrdered, onChannelRestart, channelPlaybackGeneration, filterActive, backHref, queueTotal, requestedItemId, requestedStartS }: { feed: FeedWindow; containerRef: React.RefObject<HTMLDivElement>; onGoToLastWatched?: () => void; onRandom: () => void; onOrdered: () => void; onChannelRestart: () => void; channelPlaybackGeneration: number; filterActive: boolean; backHref: string | null; queueTotal: number; requestedItemId: number | null; requestedStartS: number | null }) {
  const { muted, toggleMuted, volume, setVolume, autoLevel, toggleAutoLevel, autoGain, setAutoGain, paused, togglePaused, setPaused, captionsEnabled, toggleCaptions } = usePlayback();
  const { activeId, transitionTargetId, setActiveId, updateItem } = feed;
  const items = feed.items ?? [];
  const randomizing = feed.switchingTo === "random";
  const randomMode = feed.kind === "random";
  const channelMode = feed.kind === "channel";
  const randomTotal = randomMode ? feed.total ?? 0 : 0;
  const filteredTotal = feed.kind === "filtered" ? feed.total ?? 0 : 0;
  const queueReadyTotal = feed.kind === "queue" ? feed.total ?? 0 : 0;
  const Speaker = muted ? SpeakerSimpleX : SpeakerSimpleHigh;
  const activeIndex = items.findIndex((item) => item.id === activeId);
  const effectivePlaybackId = playbackItemId(activeId, transitionTargetId);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [settingsItem, setSettingsItem] = useState<Item | null>(null);
  const [identifyItem, setIdentifyItem] = useState<Item | null>(null);
  const [commentsItem, setCommentsItem] = useState<Item | null>(null);
  const [channelAdvanceFromId, setChannelAdvanceFromId] = useState<number | null>(null);
  const [autoAdvance, setAutoAdvance] = useState(() => localStorage.getItem("feed-auto-advance") === "true");
  // The panel is on unless the reader turned it off, and that choice sticks
  // across posts and sessions rather than being re-decided every scroll.
  const [panelOpen, setPanelOpen] = useState(() => localStorage.getItem("feed-details-panel") !== "false");
  const [commentsOpen, setCommentsOpen] = useState(false);
  // Fullscreen targets the non-scrolling wrapper: the control overlays hang off
  // it (staying pinned while the feed scrolls) and remain visible in fullscreen.
  const wrapperRef = useRef<HTMLDivElement>(null);

  const advanceAfterEnd = useCallback((itemId: number) => {
    if (channelMode) { setChannelAdvanceFromId(itemId); return; }
    if (!autoAdvance || activeId !== itemId) return;
    const nextId = nextAutoAdvanceItem(items, itemId);
    if (nextId == null) return;
    setActiveId(nextId);
    containerRef.current?.querySelector<HTMLElement>(`[data-id="${nextId}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [activeId, autoAdvance, channelMode, containerRef, items, setActiveId]);

  useEffect(() => { localStorage.setItem("feed-auto-advance", String(autoAdvance)); }, [autoAdvance]);

  useEffect(() => { localStorage.setItem("feed-details-panel", String(panelOpen)); }, [panelOpen]);


  const toggleFullscreen = useCallback(async () => {
    const target = wrapperRef.current;
    if (!target) return;
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await target.requestFullscreen();
    } catch {
      // Fullscreen can be denied by browser policy; playback still works normally.
    }
  }, []);

  useEffect(() => {
    const updateFullscreen = () => setFullscreen(document.fullscreenElement === wrapperRef.current);
    document.addEventListener("fullscreenchange", updateFullscreen);
    updateFullscreen();
    return () => document.removeEventListener("fullscreenchange", updateFullscreen);
  }, []);

  useEffect(() => {
    setPaused(false);
    setAutoGain(1);
  }, [activeId, setAutoGain, setPaused]);

  useEffect(() => {
    if (!channelMode) {
      setChannelAdvanceFromId(null);
      return;
    }
    if (channelAdvanceFromId == null) return;
    if (activeId !== channelAdvanceFromId) {
      setChannelAdvanceFromId(null);
      return;
    }
    const action = channelAdvanceAction(items, activeId, feed.activePosition, feed.total);
    if (action.kind === "wait") return;
    setChannelAdvanceFromId(null);
    if (action.kind === "restart") {
      onChannelRestart();
      return;
    }
    setActiveId(action.itemId);
    containerRef.current?.querySelector<HTMLElement>(`[data-id="${action.itemId}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [activeId, channelAdvanceFromId, channelMode, containerRef, feed.activePosition, feed.total, items, onChannelRestart, setActiveId]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const shortcut = viewerShortcut({
        key: event.key,
        code: event.code,
        repeat: event.repeat,
        editing: Boolean(target?.closest("input, textarea, [contenteditable='true']")),
        onControl: Boolean(target?.closest("button, a, select")),
      });
      if (!shortcut) return;
      if (shortcut === "pause") { event.preventDefault(); togglePaused(); return; }
      if (shortcut === "mute") { event.preventDefault(); toggleMuted(); return; }
      if (shortcut === "fullscreen") { event.preventDefault(); void toggleFullscreen(); return; }
      if (shortcut === "details") { event.preventDefault(); setPanelOpen((value) => !value); return; }
      if (shortcut === "prevImage" || shortcut === "nextImage") {
        event.preventDefault();
        // Seam: "viewer-slide-nav" — keyboard slide navigation reaches the active
        // SlideMedia (components/PostMedia.tsx) through this window CustomEvent,
        // because the slideshow index lives inside the media component.
        window.dispatchEvent(new CustomEvent("viewer-slide-nav", { detail: { delta: shortcut === "nextImage" ? 1 : -1 } }));
        return;
      }
      const delta = shortcut === "next" ? 1 : -1;
      const nextIndex = Math.max(0, Math.min(items.length - 1, (activeIndex < 0 ? 0 : activeIndex) + delta));
      if (nextIndex === activeIndex) return;
      event.preventDefault();
      const next = items[nextIndex];
      setActiveId(next.id);
      containerRef.current?.querySelector<HTMLElement>(`[data-id="${next.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activeIndex, containerRef, items, setActiveId, toggleFullscreen, toggleMuted, togglePaused]);

  return (
    <div ref={wrapperRef} className="relative h-full bg-black">
      <p className="sr-only" aria-live="polite">{paused ? "Paused" : "Playing"}</p>
      <div className="absolute left-3 top-3 z-20 flex items-center gap-1 rounded-xl border border-white/10 bg-black/55 p-1 text-white shadow-lg shadow-black/25 backdrop-blur-md">
        {onGoToLastWatched && <><button onClick={onGoToLastWatched} aria-label="Go to last watched" title="Return to the last favorite you watched" className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition hover:bg-white/15 active:translate-y-px"><ClockCounterClockwise size={16} /><span>Last watched</span></button><span aria-hidden="true" className="mx-0.5 h-5 w-px bg-white/15" /></>}
        <button onClick={onRandom} disabled={randomizing} aria-label="Start a fresh random order" title="Shuffle the archive" className="rounded-lg p-2 transition hover:bg-white/15 disabled:opacity-50"><Shuffle size={17} /></button>
        {!channelMode && <button onClick={() => setAutoAdvance((value) => !value)} aria-label="Automatically advance when media ends" aria-pressed={autoAdvance} title={autoAdvance ? "Auto-advance is on" : "Auto-advance is off"} className={`rounded-lg p-2 transition hover:bg-white/15 ${autoAdvance ? "bg-white/20" : ""}`}><ArrowDown size={17} /></button>}
        <button onClick={() => setShowShortcuts((value) => !value)} aria-label="Show keyboard shortcuts" aria-expanded={showShortcuts} title="Keyboard shortcuts" className="rounded-lg p-2 transition hover:bg-white/15"><Keyboard size={17} /></button>
        <button onClick={() => void toggleFullscreen()} aria-label={fullscreen ? "Exit fullscreen" : "Enter fullscreen"} aria-pressed={fullscreen} title={fullscreen ? "Exit fullscreen" : "Enter fullscreen"} className="rounded-lg p-2 transition hover:bg-white/15"><CornersOut size={17} /></button>
      </div>
      {randomMode && <div className="absolute left-3 top-16 z-20 flex items-center gap-2 rounded-lg border border-white/10 bg-black/55 px-2.5 py-1.5 text-xs text-white shadow-lg backdrop-blur-md">Random · {feed.activePosition == null ? "…" : feed.activePosition + 1} / {randomTotal}<button onClick={onOrdered} className="text-white/70 underline underline-offset-2 hover:text-white">Ordered feed</button></div>}
      {channelMode && <div className="absolute left-3 top-16 z-20 rounded-lg border border-white/10 bg-black/55 px-2.5 py-1.5 text-xs text-white shadow-lg backdrop-blur-md">{feed.label ?? "Archive channel"} · {feed.activePosition == null ? "…" : feed.activePosition + 1} / {feed.total ?? "…"}</div>}
      {!randomMode && queueTotal > 0 && <div className="absolute left-3 top-16 z-20 rounded-lg border border-white/10 bg-black/55 px-2.5 py-1.5 text-xs text-white shadow-lg backdrop-blur-md">Gallery queue · {queueReadyTotal} ready of {queueTotal} selected</div>}
      {!randomMode && queueTotal === 0 && (backHref || filterActive) && <div className="absolute left-3 top-16 z-20 flex items-center gap-2 rounded-lg border border-white/10 bg-black/55 px-2.5 py-1.5 text-xs text-white shadow-lg backdrop-blur-md">{backHref ? <Link to={backHref} state={{ restore: true }} className="inline-flex items-center gap-1 font-medium hover:underline"><ArrowLeft size={13} weight="bold" /> {filterActive ? "Back to results" : "Back to gallery"}</Link> : <span>Search results</span>}{filterActive && <span className="text-white/70">· {filteredTotal}</span>}</div>}
      {showShortcuts && <div className={`absolute left-3 z-20 rounded-xl border border-white/10 bg-black/70 px-3 py-2 text-xs leading-5 text-white shadow-xl backdrop-blur-md ${randomMode || channelMode || queueTotal > 0 || filterActive ? "top-28" : "top-16"}`}>↑ ↓: previous or next post<br />← →: slideshow image<br />Space or video click: play or pause<br />M: mute or unmute<br />F: enter or exit fullscreen<br />C: show or hide the details panel</div>}
      <div ref={containerRef} className="no-scrollbar h-full snap-y snap-mandatory overflow-y-scroll">
      {items.map((item, index) => (
        <PostSection
          key={item.id}
          item={item}
          active={item.id === activeId}
          playing={item.id === effectivePlaybackId}
          preload={shouldPreloadItem(index, activeIndex, item.id, transitionTargetId)}
          startAtS={item.id === requestedItemId ? requestedStartS : null}
          mediaKey={channelMediaKey(item.id, channelMode, channelPlaybackGeneration)}
          loop={!channelMode && !autoAdvance}
          onEnded={channelMode || autoAdvance ? () => advanceAfterEnd(item.id) : undefined}
          panelOpen={panelOpen}
          onTogglePanel={() => setPanelOpen((value) => !value)}
          commentsOpen={commentsOpen}
          onToggleComments={() => setCommentsOpen((value) => !value)}
          controls={

          <div className={cx("flex items-center rounded-full bg-black/45 p-1.5 text-white backdrop-blur-sm", panelOpen ? "w-full justify-end gap-1.5" : "gap-2")}>
            {(item.has_audio === false || item.audio_silent === true) && <span title="No sound — no audio stream, or a stream that is silent" className="inline-flex items-center gap-1 rounded-full bg-bad/90 px-2 py-1 text-[11px] font-semibold"><SpeakerSlash size={13} weight="fill" />{audioStatus(item.has_audio, item.audio_silent)}</span>}
            <button
              onClick={toggleMuted}
              aria-label={muted ? "Unmute" : "Mute"}
              className="rounded-full p-1.5 transition hover:bg-white/15 active:translate-y-px"
            >
              <Speaker size={20} weight="fill" />
            </button>
            <label className="hidden items-center gap-2 text-[11px] text-white/75 sm:flex">
              <span className="sr-only">Playback volume</span>
              <input
                aria-label="Playback volume"
                type="range"
                min="0"
                max="100"
                value={Math.round(volume * 100)}
                onChange={(event) => setVolume(Number(event.target.value) / 100)}
                className={cx("h-1 cursor-pointer accent-white", panelOpen ? "w-14" : "w-20")}
              />
              <span className="tabular w-7 text-right">{Math.round(volume * 100)}%</span>
            </label>
            <button
              onClick={toggleAutoLevel}
              aria-label={autoLevel ? "Disable automatic loudness leveling" : "Enable automatic loudness leveling"}
              aria-pressed={autoLevel}
              title="Automatically balances quiet and loud videos"
              className={`hidden min-w-[72px] rounded-full px-2 py-1 text-[11px] font-semibold tabular-nums transition sm:block ${autoLevel ? "bg-white text-black" : "text-white/75 hover:bg-white/15"}`}
            >
              {autoLevel ? formatAutoGain(autoGain) : "Auto off"}
            </button>
            {item.video_url && <button
              type="button"
              onClick={toggleCaptions}
              aria-label={captionsEnabled ? "Hide imported transcript captions" : "Show imported transcript captions"}
              aria-pressed={captionsEnabled}
              title={captionsEnabled ? "Hide imported transcript captions" : "Show imported transcript captions"}
              className={`min-w-9 rounded-full px-2 py-1 text-[11px] font-bold tracking-wide transition ${captionsEnabled ? "bg-white text-black" : "text-white/75 hover:bg-white/15"}`}
            >
              CC
            </button>}
            {item.video_url && <button type="button" onClick={() => setIdentifyItem(item)} aria-label={`Identify the song for favorite #${item.id}`} title="Identify or fix the song" className="rounded-full p-1.5 transition hover:bg-white/15 active:translate-y-px"><MusicNotes size={20} /></button>}
            <button type="button" onClick={() => setCommentsItem(item)} aria-label={`View comments for favorite #${item.id}`} title="View saved comments" className="rounded-full p-1.5 transition hover:bg-white/15 active:translate-y-px"><ChatCircle size={20} /></button>
            {item.video_url && <button type="button" onClick={() => setSettingsItem(item)} aria-label={`Open media settings for favorite #${item.id}`} title="Replace video or thumbnail" className="rounded-full p-1.5 transition hover:bg-white/15 active:translate-y-px"><GearSix size={20} /></button>}
          </div>
          }
        />
      ))}
      </div>
      {settingsItem && <MediaSettingsDialog item={settingsItem} onClose={() => setSettingsItem(null)} onSaved={(updated) => { updateItem(updated); setSettingsItem(null); }} />}
      {identifyItem && <SongIdentifyDialog item={identifyItem} onClose={() => setIdentifyItem(null)} onSaved={(updated) => { updateItem(updated); setIdentifyItem(null); }} />}
      {commentsItem && <CommentsDialog item={commentsItem} onClose={() => setCommentsItem(null)} />}
    </div>
  );
}


/**
 * One full-height post: the picture, its overlay controls, and the details
 * panel floating beside it.
 *
 * The panel always floats, so it reads the same on every post and the media
 * never resizes underneath you. A vertical post leaves plenty of black space
 * for it to land in; a wide one gives up its right edge, which is what the
 * toggle is for.
 */
function PostSection({
  item, active, playing, preload, startAtS, mediaKey,
  loop, onEnded, panelOpen, onTogglePanel, commentsOpen, onToggleComments, controls,
}: {
  item: Item;
  active: boolean;
  playing: boolean;
  preload: boolean;
  startAtS: number | null;
  mediaKey: string;
  loop: boolean;
  onEnded?: () => void;
  panelOpen: boolean;
  onTogglePanel: () => void;
  commentsOpen: boolean;
  onToggleComments: () => void;
  controls: React.ReactNode;
}) {
  const panelToggle = (position: React.CSSProperties) => (
    <button
      type="button"
      onClick={onTogglePanel}
      aria-expanded={panelOpen}
      aria-label={panelOpen ? "Hide post details" : "Show post details"}
      title={panelOpen ? "Hide post details (C)" : "Show post details (C)"}
      style={position}
      className="absolute top-1/2 z-40 flex h-16 w-6 -translate-y-1/2 items-center justify-center rounded-l-lg border border-r-0 border-white/15 bg-black/60 text-white backdrop-blur-md transition hover:bg-black/85 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <CaretRight size={14} weight="bold" className={cx("transition", panelOpen ? "" : "rotate-180")} />
    </button>
  );

  return (
    <section data-id={item.id} className="relative flex h-full snap-start">
      <div className="relative flex min-w-0 flex-1 items-center justify-center">
        <PostMedia
          key={mediaKey}
          item={item}
          active={playing}
          preload={preload}
          startAtS={startAtS}
          loop={loop}
          onEnded={onEnded}
        />
      </div>

      {/* Controls and panel stack in one column so they line up and match. */}
      <div
        style={{ width: panelOpen ? PANEL_WIDTH : undefined }}
        className={cx(
          "absolute right-3 top-3 z-30 flex flex-col items-end gap-2",
          commentsOpen ? "bottom-3" : "max-h-[calc(100%-1.5rem)]",
        )}
      >
        {controls}
        {panelOpen && (
          <div className="relative min-h-0 w-full flex-1">
            <PostDetailsPanel item={item} active={active} open={commentsOpen} onToggle={onToggleComments} />
            {/* Rides the panel's own left edge, so a short collapsed card keeps
                its handle beside it instead of stranded down the screen. */}
            {panelToggle({ right: "100%" })}
          </div>
        )}
      </div>

      {!panelOpen && panelToggle({ right: 0 })}
    </section>
  );
}

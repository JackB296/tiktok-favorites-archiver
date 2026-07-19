import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  MagnifyingGlass,
  Play,
  ImageSquare,
  SlidersHorizontal,
  BookmarkSimple,
  Trash,
  X,
  LinkSimple,
  Info,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { MarkAction } from "../lib/api";
import type { GalleryPreset, GalleryTermList, Item, PlaybackQueue, SearchSuggestions, SmartCollectionSummary } from "../lib/types";
import { Button, ConfirmDialog, Dialog, EmptyState, HelpLabel, Skeleton, cx } from "../components/ui";
import { VirtualGalleryGrid } from "../components/VirtualGalleryGrid";
import { GalleryThumbnail } from "../components/GalleryThumbnail";
import { canLoadNextPage, autoFillColumns, readGallerySize, shouldLoadMore } from "../lib/virtualGrid";
import type { GallerySize } from "../lib/virtualGrid";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import { useDryRunConfirm } from "../lib/useDryRunConfirm";
import {
  galleryPageRequestDelay,
  readGalleryDetails,
  readGalleryHoverPreviews,
} from "../lib/galleryPresentation.js";
import type { GalleryDetails } from "../lib/galleryPresentation.js";
import { audioStatus, formatDuration, formatSize, isSafeHttpUrl } from "../lib/format";
import { primarySongUrl, songLabel } from "../lib/songLinks.js";
import { isFeedItem } from "../lib/feedItems";
import { activeChips, filtersKey, filtersToMarkSelector, filtersToPageQuery, filtersToPreset, filtersToSearchParams } from "../lib/galleryFilters";
import type { GalleryOrder } from "../lib/galleryFilters";
import { useGalleryFilters } from "../lib/useGalleryFilters";
import { useSavedList } from "../lib/useSavedList";
import { smartCollectionConfirmation } from "../lib/smartCollectionPresentation";

const FILTERS = [
  { key: "", label: "All", help: "Show every favorite that matches the search and advanced filters." },
  { key: "video", label: "Videos", help: "Show favorites archived as ordinary video posts." },
  { key: "slideshow", label: "Slideshows", help: "Show photo posts rebuilt as playable slideshows, with original assets when available." },
];

const SIZE_LABELS: Record<GallerySize, string> = { s: "Small", m: "Medium", l: "Large", xl: "Extra large" };
const HOVER_PREVIEWS_STORAGE_KEY = "gallery-hover-previews";

/** Snapshot of a Gallery view (loaded items + scroll) so the Feed's Back button
    can restore the exact same page and scroll position. Keyed by the filter query;
    only applied when returning via that Back button (router state `restore`). */
type GalleryReturnState = { key: string; items: Item[]; nextCursor: number | null; scrollTop: number };
let galleryReturnState: GalleryReturnState | null = null;

export function Gallery() {
  const navigate = useNavigate();
  const location = useLocation();
  const scrollRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<() => void>(() => {});
  const loadingMoreRef = useRef(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const restoreRef = useRef<GalleryReturnState | null>(
    (location.state as { restore?: boolean } | null)?.restore && galleryReturnState && galleryReturnState.key === searchParams.toString()
      ? galleryReturnState
      : null,
  );
  const filters = useGalleryFilters(searchParams);
  const { state: filterState, randomSeed, set: setFilter, clearField: clearFilter } = filters;
  const { search, kind, status, order, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, audio, offloaded, indexState, include, exclude } = filterState;
  const [suggestions, setSuggestions] = useState<SearchSuggestions | null>(null);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestActive, setSuggestActive] = useState(-1);
  const [items, setItems] = useState<Item[] | null>(() => restoreRef.current?.items ?? null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const initialLoadingPhase = useDelayedLoading(items === null);
  const [nextCursor, setNextCursor] = useState<number | null>(() => restoreRef.current?.nextCursor ?? null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailed, setLoadMoreFailed] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [recoveryInboxBusy, setRecoveryInboxBusy] = useState(false);
  const [recoveryInboxMessage, setRecoveryInboxMessage] = useState<string | null>(null);
  const [smartSummary, setSmartSummary] = useState<SmartCollectionSummary | null>(null);
  const [smartBusy, setSmartBusy] = useState(false);
  const {
    items: presets, selectedId: selectedPresetId, setSelectedId: setSelectedPresetId,
    name: presetName, setName: setPresetName, message: presetMessage, setMessage: setPresetMessage,
    save: savePreset, remove: deletePreset,
  } = useSavedList<GalleryPreset>({
    load: api.galleryPresets,
    create: (name) => api.createGalleryPreset(name, filtersToPreset(filterState)),
    remove: (id) => api.deleteGalleryPreset(id),
    messages: { loadError: "Could not load saved filters.", saved: "Saved.", deleted: "Deleted." },
  });
  const [termListMode, setTermListMode] = useState<"include" | "exclude">("exclude");
  const [termListTerms, setTermListTerms] = useState("");
  const {
    items: termLists, selectedId: selectedTermListId, setSelectedId: setSelectedTermListId,
    name: termListName, setName: setTermListName, message: termListMessage, setMessage: setTermListMessage,
    save: saveTermListEntry, remove: deleteTermList,
  } = useSavedList<GalleryTermList>({
    load: api.galleryTermLists,
    create: (name) => api.createGalleryTermList(name, termListMode, parsedTerms(termListTerms)),
    remove: (id) => api.deleteGalleryTermList(id),
    messages: { loadError: "Could not load saved term lists.", saved: "Saved.", deleted: "Deleted." },
  });
  const {
    items: playbackQueues, selectedId: selectedPlaybackQueueId, setSelectedId: setSelectedPlaybackQueueId,
    name: playbackQueueName, setName: setPlaybackQueueName, message: playbackQueueMessage,
    save: savePlaybackQueueEntry, remove: deletePlaybackQueue,
  } = useSavedList<PlaybackQueue>({
    load: api.playbackQueues,
    create: (name) => api.createPlaybackQueue(name, Array.from(selectedIds)),
    remove: (id) => api.deletePlaybackQueue(id),
    messages: { loadError: "Could not load saved playback queues.", saved: "Saved.", deleted: "Deleted." },
  });
  const [size, setSize] = useState<GallerySize>(() => readGallerySize(localStorage.getItem("gallery-size")));
  const [hoverPreviews, setHoverPreviews] = useState(() => readGalleryHoverPreviews(localStorage.getItem(HOVER_PREVIEWS_STORAGE_KEY)));
  const [previewItemId, setPreviewItemId] = useState<number | null>(null);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [cardDetails, setCardDetails] = useState<GalleryDetails>(() => readGalleryDetails(localStorage.getItem("gallery-card-details")));
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [inspectionMode, setInspectionMode] = useState(false);
  const [inspectedItem, setInspectedItem] = useState<Item | null>(null);

  const pageQuery = filtersToPageQuery(filterState, randomSeed);
  const currentFiltersKey = filtersKey(filterState);

  const queryVersion = useRef(0);
  const previousPageRequestKey = useRef<string | null>(null);

  /** "Mark all matching offloaded / ignored": dry-run for a count, confirm, apply. */
  const filterAction = useDryRunConfirm<"offload" | "ignore">({
    preview: async (action) => (await api.markItems(action, { filter: filtersToMarkSelector(filterState) }, true)).matched,
    apply: async (action) => {
      const version = queryVersion.current;
      const result = await api.markItems(action, { filter: filtersToMarkSelector(filterState) });
      try {
        const page = await api.itemPage(pageQuery);
        if (version === queryVersion.current) {
          // Replace the page only if the filters haven't changed mid-flight;
          // bump the version so any in-flight loadMore append is discarded too.
          queryVersion.current += 1;
          setItems(page.items);
          setNextCursor(page.next_cursor);
        }
      } catch {
        // The marks landed — a failed refetch just leaves the page stale, and
        // the next filter change or reload refreshes it.
      }
      return `${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.`;
    },
    emptyMessage: "No favorites match the current filters.",
    cancelMessage: "Cancelled.",
  });

  useEffect(() => {
    const presetId = Number(selectedPresetId);
    if (!presetId) {
      setSmartSummary(null);
      return;
    }
    let alive = true;
    api.smartCollectionSummary(presetId)
      .then((summary) => { if (alive) setSmartSummary(summary); })
      .catch((error) => { if (alive) setPresetMessage((error as Error).message); });
    return () => { alive = false; };
  }, [selectedPresetId, setPresetMessage]);

  async function playSmartCollection() {
    const presetId = Number(selectedPresetId);
    if (!presetId) return;
    setSmartBusy(true);
    try {
      const summary = await api.smartCollectionSummary(presetId);
      if (!summary.first_item_id) {
        setPresetMessage("This Smart collection is empty.");
        return;
      }
      navigate(`/?preset=${presetId}&item=${summary.first_item_id}`);
    } catch (error) {
      setPresetMessage((error as Error).message);
    } finally {
      setSmartBusy(false);
    }
  }

  async function markSmartCollection(action: "offload" | "ignore") {
    const presetId = Number(selectedPresetId);
    if (!presetId) return;
    setSmartBusy(true);
    try {
      const preview = await api.smartCollectionMark(presetId, action, true);
      if (!preview.matched) {
        setPresetMessage("This Smart collection is empty.");
        return;
      }
      if (!window.confirm(smartCollectionConfirmation(action, preview.matched))) return;
      const result = await api.smartCollectionMark(presetId, action);
      setPresetMessage(`${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.`);
      setSmartSummary(await api.smartCollectionSummary(presetId));
      setReloadNonce((value) => value + 1);
    } catch (error) {
      setPresetMessage((error as Error).message);
    } finally {
      setSmartBusy(false);
    }
  }

  // Restore scroll position when returning to a cached Gallery view via Back. Retry
  // across a few frames so the virtual grid has time to compute its full height.
  useEffect(() => {
    if (!restoreRef.current) return;
    const target = restoreRef.current.scrollTop;
    let cancelled = false;
    const apply = () => { if (!cancelled && scrollRef.current) scrollRef.current.scrollTop = target; };
    const timers = [0, 50, 150, 300, 500].map((delay) => window.setTimeout(apply, delay));
    return () => { cancelled = true; timers.forEach((t) => window.clearTimeout(t)); };
  }, []);

  useEffect(() => {
    // Returning from the Feed via Back keeps the restored items + scroll — don't refetch.
    if (restoreRef.current) {
      if (restoreRef.current.key === currentFiltersKey) return;
      restoreRef.current = null;
    }
    let alive = true;
    queryVersion.current += 1;
    setLoadError(null);
    setLoadMoreFailed(false);
    const requestKey = `${currentFiltersKey}\0${randomSeed}\0${reloadNonce}`;
    const delay = galleryPageRequestDelay(previousPageRequestKey.current, requestKey);
    previousPageRequestKey.current = requestKey;
    const requestPage = () => {
      api
        .itemPage(pageQuery)
        .then((page) => {
          if (!alive) return;
          setItems(page.items);
          setNextCursor(page.next_cursor);
        })
        .catch((error) => {
          if (!alive) return;
          setItems([]);
          setLoadError((error as Error).message || "Request failed");
        });
    };
    let timer: number | null = null;
    if (delay === 0) requestPage();
    else timer = window.setTimeout(requestPage, delay);
    return () => {
      alive = false;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [currentFiltersKey, randomSeed, reloadNonce]);

  useEffect(() => {
    setSelectedIds(new Set());
    setRecoveryMessage(null);
  }, [currentFiltersKey, randomSeed]);

  // Typeahead: debounce keystrokes, then ask the archive what it actually has.
  useEffect(() => {
    const q = search.trim();
    if (!q) { setSuggestions(null); return; }
    let alive = true;
    const t = window.setTimeout(() => {
      api.suggest(q).then((next) => { if (alive) setSuggestions(next); }).catch(() => { if (alive) setSuggestions(null); });
    }, 150);
    return () => { alive = false; window.clearTimeout(t); };
  }, [search]);

  useEffect(() => { setSuggestActive(-1); }, [suggestions]);

  useEffect(() => {
    // Only rewrite the URL when it's actually out of sync — a redundant replace()
    // would wipe navigation state (the Back-button `restore` flag) on mount.
    const next = filtersToSearchParams(filterState);
    if (next.toString() !== searchParams.toString()) setSearchParams(next, { replace: true });
  }, [currentFiltersKey, searchParams, setSearchParams]);

  function parsedTerms(value: string) {
    return Array.from(new Set(value.split(",").map((term) => term.trim()).filter(Boolean)));
  }

  function applyTermList() {
    const list = termLists.find((item) => item.id === Number(selectedTermListId));
    if (!list) return;
    const merged = Array.from(new Set([...parsedTerms(list.mode === "include" ? include : exclude), ...list.terms]));
    if (list.mode === "include") setFilter("include", merged.join(", "));
    else setFilter("exclude", merged.join(", "));
    setTermListMessage(`${list.name} applied.`);
  }

  async function saveTermList() {
    if (!parsedTerms(termListTerms).length) return;
    const saved = await saveTermListEntry();
    if (saved) setTermListTerms("");
  }

  async function loadMore() {
    if (!canLoadNextPage(nextCursor, loadingMoreRef.current)) return;
    const version = queryVersion.current;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const page = await api.itemPage({ ...pageQuery, cursor: nextCursor });
      if (version !== queryVersion.current) return; // filters changed mid-flight
      setItems((current) => [...(current ?? []), ...page.items]);
      setNextCursor(page.next_cursor);
      setLoadMoreFailed(false);
    } catch {
      if (version === queryVersion.current) setLoadMoreFailed(true);
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }

  useEffect(() => {
    loadMoreRef.current = () => { void loadMore(); };
  });

  useEffect(() => {
    const scroller = scrollRef.current;
    if (!scroller || nextCursor == null) return;
    let frame = 0;
    const maybeLoad = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        if (shouldLoadMore(scroller.scrollTop, scroller.clientHeight, scroller.scrollHeight, 1_600)) loadMoreRef.current();
      });
    };
    scroller.addEventListener("scroll", maybeLoad, { passive: true });
    maybeLoad();
    return () => {
      window.cancelAnimationFrame(frame);
      scroller.removeEventListener("scroll", maybeLoad);
    };
  }, [items?.length, loadingMore, nextCursor]);

  async function copyFilteredLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setPresetMessage("Filtered link copied.");
    } catch {
      setPresetMessage("Could not copy the link.");
    }
  }

  function changeSize(next: GallerySize) {
    setSize(next);
    localStorage.setItem("gallery-size", next);
  }

  function changeHoverPreviews(enabled: boolean) {
    setHoverPreviews(enabled);
    localStorage.setItem(HOVER_PREVIEWS_STORAGE_KEY, String(enabled));
    if (!enabled) setPreviewItemId(null);
  }

  const startHoverPreview = useCallback((itemId: number) => {
    setPreviewItemId(itemId);
  }, []);

  const stopHoverPreview = useCallback((itemId: number) => {
    setPreviewItemId((current) => current === itemId ? null : current);
  }, []);

  useEffect(() => {
    if (!hoverPreviews || selectionMode || inspectionMode) setPreviewItemId(null);
  }, [hoverPreviews, inspectionMode, selectionMode]);

  function changeCardDetail(key: keyof GalleryDetails, shown: boolean) {
    setCardDetails((current) => {
      const next = { ...current, [key]: shown };
      localStorage.setItem("gallery-card-details", JSON.stringify(next));
      return next;
    });
  }

  function clearAllFilters() {
    filters.clear();
    setRecoveryInboxMessage(null);
    setSelectedPresetId("");
  }

  function toggleSelection(itemId: number) {
    if (!selectedIds.has(itemId) && selectedIds.size >= 100) {
      setRecoveryMessage("A selection can contain up to 100 favorites.");
      return;
    }
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(itemId)) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  function leaveSelectionMode() {
    setSelectionMode(false);
    setSelectedIds(new Set());
  }

  function playSelected() {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    navigate(`/?queue=${ids.join(",")}`);
  }

  async function savePlaybackQueue() {
    if (!selectedIds.size) return;
    await savePlaybackQueueEntry();
  }

  function playSavedQueue() {
    const queue = playbackQueues.find((item) => item.id === Number(selectedPlaybackQueueId));
    if (queue) navigate(`/?queue=${queue.item_ids.join(",")}`);
  }

  function enterSelectionMode() {
    setInspectionMode(false);
    setInspectedItem(null);
    setSelectionMode(true);
  }

  async function requeueSelected() {
    const ids = Array.from(selectedIds);
    if (!ids.length || recoveryBusy) return;
    setRecoveryBusy(true);
    setRecoveryMessage(null);
    try {
      const result = await api.requeueItems(ids);
      const requeued = new Set(result.requeued);
      setItems((current) => current?.flatMap((item) => {
        if (!requeued.has(item.id)) return [item];
        return status === "failed" ? [] : [{ ...item, status: "pending" }];
      }) ?? current);
      setSelectedIds(new Set());
      setRecoveryMessage(
        result.requeued.length
          ? `${result.requeued.length} item${result.requeued.length === 1 ? "" : "s"} queued for the next Sync.${result.skipped ? ` ${result.skipped} left unchanged.` : ""}`
          : "No selected items needed recovery.",
      );
    } catch (error) {
      setRecoveryMessage((error as Error).message);
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function markSelected(action: MarkAction) {
    const ids = Array.from(selectedIds);
    if (!ids.length || recoveryBusy) return;
    setRecoveryBusy(true);
    setRecoveryMessage(null);
    try {
      const version = queryVersion.current;
      const result = await api.markItems(action, { ids });
      try {
        // A failed refresh must not read as a failed mark — the mutation
        // already committed; stale items just wait for the next load.
        const page = await api.itemPage(pageQuery);
        if (version === queryVersion.current) {
          // Replace the page only if the filters haven't changed mid-flight;
          // bump the version so any in-flight loadMore append is discarded too.
          queryVersion.current += 1;
          setItems(page.items);
          setNextCursor(page.next_cursor);
        }
      } catch {
        // refresh failure ignored; success message below still applies
      }
      setSelectedIds(new Set());
      const requeued = result.requeued ? ` ${result.requeued} had no local video and returned to the download queue.` : "";
      setRecoveryMessage(`${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.${requeued}`);
    } catch (error) {
      setRecoveryMessage((error as Error).message);
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function retryItem(id: number) {
    setInspectedItem(null);
    try {
      await api.requeueItems([id]);
    } catch (error) {
      setRecoveryInboxMessage(`Could not queue favorite #${id} for the next Sync: ${(error as Error).message}`);
      return; // nothing changed, so keep the current page
    }
    setRecoveryInboxMessage(null);
    restoreRef.current = null; // force a fresh page so the change shows
    setReloadNonce((n) => n + 1);
  }

  async function ignoreItem(id: number, ignored: boolean) {
    setInspectedItem(null);
    try {
      await api.markItems(ignored ? "unignore" : "ignore", { ids: [id] });
    } catch (error) {
      setRecoveryInboxMessage(`Could not update favorite #${id}: ${(error as Error).message}`);
      return; // nothing changed, so keep the current page
    }
    setRecoveryInboxMessage(null);
    restoreRef.current = null;
    setReloadNonce((n) => n + 1);
  }

  /** Open a favorite in the Feed. With an active search/filter, scope the Feed to
      the whole matching set in the current sort order; otherwise open the archive. */
  function openInFeed(itemId: number) {
    const params = new URLSearchParams(filtersToMarkSelector(filterState));
    if (order !== "latest") params.set("order", order);
    if (order === "random") params.set("seed", String(randomSeed));
    const from = currentFiltersKey;
    // Snapshot this view so the Feed's Back button restores it at the same scroll spot.
    galleryReturnState = { key: from, items: items ?? [], nextCursor, scrollTop: scrollRef.current?.scrollTop ?? 0 };
    params.set("from", from);
    params.set("item", String(itemId));
    navigate(`/?${params.toString()}`);
  }

  async function toggleRecoveryInbox() {
    if (recovery) {
      setFilter("recovery", false);
      setRecoveryInboxMessage(null);
      return;
    }
    setRecoveryInboxBusy(true);
    setRecoveryInboxMessage(null);
    try {
      await api.verify();
      setFilter("recovery", true);
      setRecoveryInboxMessage("Integrity check complete. Showing failed, missing, and never-tried favorites.");
    } catch (error) {
      setRecoveryInboxMessage(`Could not refresh archive integrity: ${(error as Error).message}`);
    } finally {
      setRecoveryInboxBusy(false);
    }
  }

  const selectedItems = (items ?? []).filter((it) => selectedIds.has(it.id));
  const allSelectedOffloaded = selectedItems.length > 0 && selectedItems.every((it) => it.offloaded);
  const allSelectedIgnored = selectedItems.length > 0 && selectedItems.every((it) => it.status === "ignored");

  const activeFilters = activeChips(filterState);

  const suggestItems = suggestions
    ? [
        ...suggestions.creators.map((c) => ({ value: c.value, kind: "Creator" })),
        ...suggestions.hashtags.map((h) => ({ value: h.value, kind: "Hashtag" })),
        ...suggestions.terms.map((t) => ({ value: t.value, kind: "Keyword" })),
      ]
    : [];
  const showSuggest = suggestOpen && suggestItems.length > 0;
  function pickSuggestion(value: string) {
    setFilter("search", value);
    setSuggestOpen(false);
    setSuggestActive(-1);
  }

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
    <div className="w-full px-[clamp(1rem,1.5vw,2.5rem)] py-6">
      <div style={{ fontSize: "clamp(14px, 8.8px + 0.34vw, 22px)" }} className="mb-6 flex flex-col gap-[0.75em] lg:flex-row lg:items-start lg:gap-[1em]">
        <div className="relative w-full lg:w-[34em] lg:shrink-0">
          <label htmlFor="gallery-search" className="sr-only">Search favorites</label>
          <MagnifyingGlass size="1.2em" className="pointer-events-none absolute left-[0.9em] top-[1.35em] -translate-y-1/2 text-ink-faint" />
          <input
            id="gallery-search"
            value={search}
            onChange={(e) => setFilter("search", e.target.value)}
            onFocus={() => setSuggestOpen(true)}
            onBlur={() => setSuggestOpen(false)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setSuggestOpen(true); setSuggestActive((i) => Math.min(i + 1, suggestItems.length - 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setSuggestActive((i) => Math.max(i - 1, 0)); }
              else if (e.key === "Enter" && showSuggest && suggestActive >= 0) { e.preventDefault(); pickSuggestion(suggestItems[suggestActive].value); }
              else if (e.key === "Escape") { setSuggestOpen(false); setSuggestActive(-1); }
            }}
            role="combobox"
            aria-expanded={showSuggest}
            aria-controls="gallery-search-suggestions"
            aria-autocomplete="list"
            placeholder="Search caption, hashtag, author"
            title="Searches indexed captions, hashtags, creator names, and source links. Best text matches appear first unless an advanced sort is selected."
            className="h-[2.7em] w-full rounded-[var(--radius-control)] border border-line bg-surface pl-[2.7em] pr-[1em] text-[1em] text-ink placeholder:text-ink-faint focus:border-accent"
          />
          {search.trim() && !showSuggest && <p className="mt-[0.4em] text-[0.75em] text-ink-faint">Best matches first. Choose an advanced sort to override relevance.</p>}
          {showSuggest && (
            <ul id="gallery-search-suggestions" role="listbox" aria-label="Search suggestions" className="absolute left-0 right-0 top-full z-20 mt-[0.35em] max-h-[60vh] overflow-auto rounded-[var(--radius-control)] border border-line bg-elevated py-[0.3em] text-[0.9em] shadow-xl">
              {suggestItems.map((opt, i) => {
                const firstOfKind = i === 0 || suggestItems[i - 1].kind !== opt.kind;
                return (
                  <li key={opt.kind + opt.value} role="option" aria-selected={i === suggestActive}>
                    {firstOfKind && <div className="px-[0.9em] pb-[0.1em] pt-[0.45em] text-[0.72em] font-semibold uppercase tracking-wide text-ink-faint">{opt.kind}</div>}
                    <button
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setSuggestActive(i)}
                      onClick={() => pickSuggestion(opt.value)}
                      className={cx("flex w-full items-center gap-[0.5em] px-[0.9em] py-[0.35em] text-left", i === suggestActive ? "bg-accent/15 text-ink" : "text-ink-dim hover:text-ink")}
                    >
                      <MagnifyingGlass size="0.9em" className="shrink-0 text-ink-faint" />
                      <span className="truncate">{opt.value}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-[0.4em] lg:flex-1 lg:justify-end">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setFilter("kind", f.key)}
              title={f.help}
              className={cx(
                "rounded-full px-[0.85em] py-[0.4em] text-[0.8em] font-medium transition",
                kind === f.key ? "bg-accent text-on-accent" : "border border-line text-ink-dim hover:text-ink",
              )}
            >
              {f.label}
            </button>
          ))}
          <div role="group" aria-label="Thumbnail size" className="inline-flex items-center gap-[0.15em] rounded-full border border-line p-[0.2em]">
            {(["s", "m", "l", "xl"] as GallerySize[]).map((opt) => (
              <button
                key={opt}
                onClick={() => changeSize(opt)}
                aria-pressed={size === opt}
                title={`${SIZE_LABELS[opt]} thumbnails`}
                className={cx(
                  "rounded-full px-[0.6em] py-[0.25em] text-[0.72em] font-semibold uppercase leading-none transition",
                  size === opt ? "bg-accent text-on-accent" : "text-ink-dim hover:text-ink",
                )}
              >
                {opt}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => changeHoverPreviews(!hoverPreviews)}
            aria-pressed={hoverPreviews}
            title="Opt in to muted six-second video samples after resting the pointer on a card. Only one preview loads at a time."
            className={cx("inline-flex items-center gap-[0.35em] rounded-full border px-[0.85em] py-[0.4em] text-[0.8em] font-medium transition", hoverPreviews ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}
          >
            <Play size="1em" weight={hoverPreviews ? "fill" : "regular"} />
            Hover previews
          </button>
          <button onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen} className={cx("rounded-full border px-[0.85em] py-[0.4em] text-[0.8em] font-medium transition", detailsOpen ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>Card details</button>
          <button onClick={() => selectionMode ? leaveSelectionMode() : enterSelectionMode()} aria-pressed={selectionMode} className={cx("rounded-full border px-[0.85em] py-[0.4em] text-[0.8em] font-medium transition", selectionMode ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>{selectionMode ? "Done selecting" : "Select"}</button>
          <button onClick={toggleRecoveryInbox} disabled={recoveryInboxBusy} aria-pressed={recovery} className={cx("rounded-full border px-[0.85em] py-[0.4em] text-[0.8em] font-medium transition disabled:opacity-40", recovery ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>{recoveryInboxBusy ? "Checking…" : recovery ? "Recovery inbox" : "Recovery"}</button>
          <button onClick={() => { if (inspectionMode) { setInspectionMode(false); setInspectedItem(null); } else { leaveSelectionMode(); setInspectionMode(true); } }} aria-pressed={inspectionMode} className={cx("rounded-full border p-[0.5em] transition", inspectionMode ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")} aria-label={inspectionMode ? "Leave inspect mode" : "Inspect Gallery metadata"}><Info size="1.1em" /></button>
          <button onClick={() => setAdvanced((value) => !value)} title="Open saved filters, whitelist and blacklist lists, playback queues, and detailed archive filters." aria-label="Toggle advanced filters" className="rounded-full border border-line p-[0.5em] text-ink-dim hover:text-ink"><SlidersHorizontal size="1.1em" /></button>
        </div>
      </div>

      {recoveryInboxMessage && <p className="mb-5 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5 text-sm text-ink-dim" role="status">{recoveryInboxMessage}</p>}

      {detailsOpen && <section className="mb-5 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-3" aria-label="Gallery card details">
        <p className="mb-2 text-xs text-ink-dim">Choose what appears over Gallery previews. Resolution is hidden by default.</p>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          {([
            ["archiveNumber", "Favorite number"],
            ["duration", "Duration"],
            ["resolution", "Resolution"],
            ["author", "Creator"],
            ["caption", "Caption"],
            ["technical", "Codec & file size"],
          ] as Array<[keyof GalleryDetails, string]>).map(([key, label]) => <label key={key} className="flex items-center gap-2 text-xs text-ink"><input type="checkbox" checked={cardDetails[key]} onChange={(event) => changeCardDetail(key, event.target.checked)} /> {label}</label>)}
        </div>
      </section>}

      {selectionMode && <section className="mb-5 flex flex-wrap items-center gap-3 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5 text-sm text-ink-dim" aria-live="polite">
        <span>{selectedIds.size} selected (up to 100)</span>
        <button type="button" onClick={() => setSelectedIds(new Set())} disabled={!selectedIds.size || recoveryBusy} className="text-ink underline underline-offset-2 disabled:opacity-40">Clear</button>
        <Button variant="ghost" size="xs" onClick={playSelected} disabled={!selectedIds.size || recoveryBusy}><Play size={14} weight="fill" /> Play selection</Button>
        <input value={playbackQueueName} onChange={(event) => setPlaybackQueueName(event.target.value)} maxLength={80} placeholder="Save as queue…" className="h-8 rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-xs text-ink placeholder:text-ink-faint" />
        <Button variant="ghost" size="xs" onClick={savePlaybackQueue} disabled={!selectedIds.size || !playbackQueueName.trim() || recoveryBusy}><BookmarkSimple size={14} /> Save queue</Button>
        <Button variant="ghost" size="xs" onClick={() => markSelected(allSelectedOffloaded ? "unoffload" : "offload")} disabled={!selectedIds.size || recoveryBusy} title="Offloaded favorites are archived on external storage, so Sync and integrity checks stop flagging them as missing.">{allSelectedOffloaded ? "Unmark offloaded" : "Mark offloaded"}</Button>
        <Button variant="ghost" size="xs" onClick={() => markSelected(allSelectedIgnored ? "unignore" : "ignore")} disabled={!selectedIds.size || recoveryBusy} title="Ignored favorites keep their place in the archive but Sync never downloads them.">{allSelectedIgnored ? "Allow downloading" : "Don't download"}</Button>
        <Button variant="ghost" size="xs" onClick={() => navigate(`/storage?ids=${Array.from(selectedIds).join(",")}`)} disabled={!selectedIds.size || recoveryBusy}>Storage…</Button>
        <Button size="xs" onClick={requeueSelected} disabled={!selectedIds.size || recoveryBusy}>{recoveryBusy ? "Queuing…" : "Queue selected for Sync"}</Button>
        <span className="text-xs text-ink-faint">Only failed favorites and finished favorites missing their file will be queued.</span>
        {recoveryMessage && <span className="w-full text-xs text-ink-dim">{recoveryMessage}</span>}
        {playbackQueueMessage && <span className="w-full text-xs text-ink-dim">{playbackQueueMessage}</span>}
      </section>}

      {inspectionMode && <p className="mb-5 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5 text-sm text-ink-dim">Inspect mode: choose a thumbnail to view its full archive metadata. Click the <Info size={13} className="inline" /> button again to return to playback clicks.</p>}

      {activeFilters.length > 0 && <div className="mb-5 flex flex-wrap items-center gap-2" aria-label="Active Gallery filters">
        <span className="text-xs text-ink-faint">Active filters</span>
        {activeFilters.map((chip) => <button key={chip.key} type="button" onClick={() => { clearFilter(chip.key); setSelectedPresetId(""); }} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-dim hover:text-ink">{chip.label}<X size={12} aria-hidden="true" /></button>)}
        <button type="button" onClick={clearAllFilters} className="px-1 text-xs text-ink-dim underline underline-offset-2 hover:text-ink">Clear all</button>
        <button type="button" onClick={copyFilteredLink} className="inline-flex items-center gap-1 px-1 text-xs text-ink-dim underline underline-offset-2 hover:text-ink"><LinkSimple size={13} /> Copy link</button>
      </div>}

      {advanced && <section className="mb-5 grid gap-4 rounded-[var(--radius-media)] border border-line bg-surface p-4">
        <div>
          <p className="text-xs font-semibold text-ink">Saved filters</p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="Applies a named snapshot of every current Gallery search, filter, and sort setting.">Saved filters</HelpLabel>
              <select value={selectedPresetId} onChange={(e) => { const preset = presets.find((item) => item.id === Number(e.target.value)); setSelectedPresetId(e.target.value); if (preset) filters.applyPreset(preset.filters); }} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Apply a saved filter…</option>{presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select>
            </label>
            <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="Names and saves the complete filter setup currently shown, including whitelist and blacklist terms.">Save current filters as</HelpLabel>
              <input value={presetName} onChange={(e) => setPresetName(e.target.value)} maxLength={80} placeholder="e.g. Games without fyp" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
            </label>
            <Button variant="ghost" size="sm" onClick={savePreset} disabled={!presetName.trim()}><BookmarkSimple size={15} /> Save</Button>
            {selectedPresetId && <Button variant="danger" size="sm" onClick={() => void deletePreset()}><Trash size={15} /> Delete</Button>}
            {presetMessage && <span className="text-xs text-ink-faint">{presetMessage}</span>}
          </div>
          {selectedPresetId && <div className="mt-3 flex flex-wrap items-center gap-2 rounded-[var(--radius-control)] border border-line bg-elevated px-3 py-2">
            <span className="mr-auto text-xs text-ink-dim"><strong className="text-ink">{smartSummary?.count ?? "…"}</strong> current favorite{smartSummary?.count === 1 ? "" : "s"} · live Smart collection</span>
            <Button variant="ghost" size="xs" onClick={() => { const preset = presets.find((item) => item.id === Number(selectedPresetId)); if (preset) filters.applyPreset(preset.filters); }} disabled={smartBusy}>Open</Button>
            <Button variant="ghost" size="xs" onClick={() => void playSmartCollection()} disabled={smartBusy || smartSummary?.count === 0}><Play size={14} weight="fill" /> Play</Button>
            <a href={api.smartCollectionInventoryUrl(Number(selectedPresetId))} className="rounded px-2 py-1 text-xs font-medium text-ink-dim hover:text-ink">CSV</a>
            <Button variant="ghost" size="xs" onClick={() => void markSmartCollection("offload")} disabled={smartBusy}>Mark offloaded</Button>
            <Button variant="ghost" size="xs" onClick={() => void markSmartCollection("ignore")} disabled={smartBusy}>Ignore</Button>
          </div>}
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Creator &amp; tag lists</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-dim sm:col-span-2"><HelpLabel help="Reusable groups of creators, hashtags, or words. Applying a list adds its terms to the matching whitelist or blacklist field.">Saved creator / tag lists</HelpLabel>
              <select value={selectedTermListId} onChange={(e) => setSelectedTermListId(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Choose a list…</option>{termLists.map((list) => <option key={list.id} value={list.id}>{list.name} · {list.mode === "include" ? "whitelist" : "blacklist"}</option>)}</select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="A descriptive name for this reusable group of whitelist or blacklist terms.">List name</HelpLabel>
              <input value={termListName} onChange={(e) => setTermListName(e.target.value)} maxLength={80} placeholder="e.g. No FYP" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Whitelist keeps only favorites matching every applied whitelist group. Blacklist removes favorites matching any applied blacklist term. You can save and use both kinds together.">List behavior</HelpLabel>
              <select value={termListMode} onChange={(e) => setTermListMode(e.target.value as "include" | "exclude")} className="mt-1 h-9 rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="exclude">Blacklist</option><option value="include">Whitelist</option></select>
            </label>
            <label className="text-xs text-ink-dim sm:col-span-2 lg:col-span-4"><HelpLabel help="Creators, hashtags, or words separated by commas. Hashtags may be entered with or without the # symbol.">Creators, tags, or words</HelpLabel>
              <input value={termListTerms} onChange={(e) => setTermListTerms(e.target.value)} placeholder="#fyp, foryou" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
            </label>
            <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-4"><Button variant="ghost" size="sm" onClick={applyTermList} disabled={!selectedTermListId}>Apply selected list</Button>{selectedTermListId && <Button variant="danger" size="sm" onClick={() => void deleteTermList()}><Trash size={15} /> Delete</Button>}<Button variant="ghost" size="sm" onClick={saveTermList} disabled={!termListName.trim() || !parsedTerms(termListTerms).length}><BookmarkSimple size={15} /> Save new list</Button>{termListMessage && <span className="text-xs text-ink-faint">{termListMessage}</span>}</div>
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Playback queues</p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="A saved ordered selection of up to 100 favorites that can be reopened in Feed later.">Saved playback queues</HelpLabel>
              <select value={selectedPlaybackQueueId} onChange={(e) => setSelectedPlaybackQueueId(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Choose a queue…</option>{playbackQueues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name} · {queue.item_ids.length} favorites</option>)}</select>
            </label>
            <Button variant="ghost" size="sm" onClick={playSavedQueue} disabled={!selectedPlaybackQueueId}><Play size={15} weight="fill" /> Play queue</Button>
            {selectedPlaybackQueueId && <Button variant="danger" size="sm" onClick={() => void deletePlaybackQueue()}><Trash size={15} /> Delete</Button>}
            {playbackQueueMessage && <span className="text-xs text-ink-faint">{playbackQueueMessage}</span>}
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Sort &amp; status</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-dim"><HelpLabel help="Controls the order of matching favorites. Random creates a fresh temporary shuffle each time it is selected.">Sort order</HelpLabel>
              <select value={order} onChange={(e) => setFilter("order", e.target.value as GalleryOrder)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="latest">Latest imported favorite</option><option value="archive">Oldest imported favorite</option><option value="favorite_date_desc">Newest favorite date</option><option value="favorite_date_asc">Oldest favorite date</option><option value="author_asc">Creator A-Z</option><option value="audio_missing">Missing audio first</option><option value="size_desc">Largest file</option><option value="duration_desc">Longest video</option><option value="duration_asc">Shortest video</option><option value="attempts_desc">Most download attempts</option><option value="last_attempt_desc">Most recently attempted</option><option value="random">Random order</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Ready has local media. Failed can be retried. Unavailable means TikTok reports the original is gone and it will not be retried automatically.">Archive status</HelpLabel>
              <select value={status} onChange={(e) => setFilter("status", e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any status</option><option value="done">Ready</option><option value="pending">Pending</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="expired">Unavailable original</option><option value="ignored">Ignored</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Shows favorites Sync has tried at least this many times, including successful and failed attempts.">Minimum download attempts</HelpLabel>
              <input value={minAttempts} onChange={(e) => setFilter("minAttempts", e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Shows favorites Sync has tried no more than this many times. Use 0 to find pending favorites never attempted.">Maximum download attempts</HelpLabel>
              <input value={maxAttempts} onChange={(e) => setFilter("maxAttempts", e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Media facts</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-dim"><HelpLabel help="Filters indexed media by its frame shape: taller than wide, wider than tall, or equal width and height.">Orientation</HelpLabel>
              <select value={orientation} onChange={(e) => setFilter("orientation", e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any orientation</option><option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="square">Square</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Filters photo posts by whether their original downloaded images and audio are still stored beside the rebuilt video.">Raw slideshow assets</HelpLabel>
              <select value={assets} onChange={(e) => setFilter("assets", e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any asset state</option><option value="with">Has original assets</option><option value="without">No original assets</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Filters videos by whether the archived file has an audio stream. 'No audio' shows silent videos — whether the original had no sound or the audio never came through.">Audio</HelpLabel>
              <select value={audio} onChange={(e) => setFilter("audio", e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any audio</option><option value="with">Has audio</option><option value="without">No audio</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Offloaded favorites are archived on external storage (like a NAS), so they have no local file here but are not missing.">External storage</HelpLabel>
              <select value={offloaded} onChange={(e) => setFilter("offloaded", e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any</option><option value="with">Offloaded</option><option value="without">Local</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Indexed favorites have a thumbnail and media facts. Missing has not been indexed yet. Failed means thumbnail or media inspection failed.">Gallery index health</HelpLabel>
              <select value={indexState} onChange={(e) => setFilter("indexState", e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any index state</option><option value="indexed">Indexed</option><option value="missing">Not indexed</option><option value="failed">Index failed</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps videos at least this many seconds long.">Minimum duration (seconds)</HelpLabel>
              <input value={minDuration} onChange={(e) => setFilter("minDuration", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps videos no longer than this many seconds.">Maximum duration (seconds)</HelpLabel>
              <input value={maxDuration} onChange={(e) => setFilter("maxDuration", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps local video files at least this large.">Minimum file size (MB)</HelpLabel>
              <input value={minSize} onChange={(e) => setFilter("minSize", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps local video files no larger than this value.">Maximum file size (MB)</HelpLabel>
              <input value={maxSize} onChange={(e) => setFilter("maxSize", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and filters by the encoded video frame width in pixels.">Minimum width (px)</HelpLabel>
              <input value={minWidth} onChange={(e) => setFilter("minWidth", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and excludes frames wider than this pixel value.">Maximum width (px)</HelpLabel>
              <input value={maxWidth} onChange={(e) => setFilter("maxWidth", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and filters by the encoded video frame height in pixels.">Minimum height (px)</HelpLabel>
              <input value={minHeight} onChange={(e) => setFilter("minHeight", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and excludes frames taller than this pixel value.">Maximum height (px)</HelpLabel>
              <input value={maxHeight} onChange={(e) => setFilter("maxHeight", e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and matches encoded video formats such as h264, hevc, or vp9. Separate alternatives with commas.">Video codec</HelpLabel>
              <input value={codec} onChange={(e) => setFilter("codec", e.target.value)} placeholder="e.g. h264, hevc" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
            </label>
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Dates &amp; terms</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-dim"><HelpLabel help="Uses the date recorded in your TikTok export and excludes favorites saved before this day.">Favorited on or after</HelpLabel>
              <input value={dateFrom} onChange={(e) => setFilter("dateFrom", e.target.value)} type="date" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Uses the date recorded in your TikTok export and excludes favorites saved after this day.">Favorited on or before</HelpLabel>
              <input value={dateTo} onChange={(e) => setFilter("dateTo", e.target.value)} type="date" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Whitelist: every comma-separated term must match the caption or creator. Use this to keep only specific creators, hashtags, or topics.">Whitelist creators / tags / words</HelpLabel><input value={include} onChange={(e) => setFilter("include", e.target.value)} placeholder="e.g. @creator, #games" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" /></label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Blacklist: any matching comma-separated term removes that favorite. Use this to hide creators, hashtags, or topics such as #fyp.">Blacklist creators / tags / words</HelpLabel><input value={exclude} onChange={(e) => setFilter("exclude", e.target.value)} placeholder="e.g. #fyp, spoilers" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" /></label>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="text-xs text-ink-dim"><HelpLabel help="Applies an archive mark to every favorite matching the current search and filters. A count is shown for confirmation before anything changes.">With these filters…</HelpLabel></span>
          <Button variant="ghost" size="sm" onClick={() => void filterAction.request("offload")} disabled={filterAction.busy}>Mark all matching offloaded</Button>
          <Button variant="ghost" size="sm" onClick={() => void filterAction.request("ignore")} disabled={filterAction.busy}>Ignore all matching</Button>
          {filterAction.message && <span className="text-xs text-ink-faint">{filterAction.message}</span>}
        </div>
      </section>}

      {!items && initialLoadingPhase === "quiet" ? (
        <div className="min-h-40" aria-busy="true" aria-label="Loading Gallery" />
      ) : initialLoadingPhase === "indicator" ? (
        <Grid size={size}>
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[9/16] !rounded-[var(--radius-media)]" />
          ))}
        </Grid>
      ) : !items ? (
        <div className="min-h-40" aria-busy="true" aria-label="Loading Gallery" />
      ) : loadError !== null ? (
        <EmptyState
          icon={<ImageSquare size={40} />}
          title="Couldn't load the Gallery"
          hint={<>{loadError}<br /><Button size="sm" className="mt-3" onClick={() => setReloadNonce((n) => n + 1)}>Try again</Button></>}
        />
      ) : !items.length ? (
        <EmptyState
          icon={<ImageSquare size={40} />}
          title="No matches"
          hint="Try a different search, or import your export and run a sync."
        />
      ) : (
        <>
          <VirtualGalleryGrid
            items={items}
            size={size}
            scrollRef={scrollRef}
            renderItem={(it, cardWidth) => <GalleryThumbnail key={it.id} item={it} cardWidth={cardWidth} details={cardDetails} selecting={selectionMode} inspecting={inspectionMode} selected={selectedIds.has(it.id)} previewEnabled={hoverPreviews && !selectionMode && !inspectionMode} previewActive={previewItemId === it.id} onPreviewStart={startHoverPreview} onPreviewEnd={stopHoverPreview} onClick={() => selectionMode ? toggleSelection(it.id) : inspectionMode || !isFeedItem(it) ? setInspectedItem(it) : openInFeed(it.id)} />}
          />
          {nextCursor != null && (
            <div className="mt-6 flex items-center justify-center gap-2 py-3 text-xs text-ink-faint" aria-live="polite" aria-busy={loadingMore}>
              {loadMoreFailed && !loadingMore ? (
                <>
                  <span>Couldn't load more — scroll or press to retry.</span>
                  <Button variant="ghost" size="xs" onClick={() => loadMoreRef.current?.()}>Retry</Button>
                </>
              ) : (
                <>
                  <span aria-hidden="true" className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-accent" />
                  <span>{loadingMore ? "Loading more favorites…" : "More favorites load as you scroll."}</span>
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
    {inspectedItem && <DetailsDialog item={inspectedItem} onClose={() => setInspectedItem(null)} onPlay={() => navigate(`/?item=${inspectedItem.id}`)} onRetry={() => retryItem(inspectedItem.id)} onIgnore={() => ignoreItem(inspectedItem.id, inspectedItem.status === "ignored")} />}
    {filterAction.pending && <ConfirmDialog
      title={filterAction.pending.payload === "offload" ? "Mark matching favorites offloaded?" : "Ignore matching favorites?"}
      message={`This will ${filterAction.pending.payload === "offload" ? "mark" : "ignore"} ${filterAction.pending.matched} favorite${filterAction.pending.matched === 1 ? "" : "s"}${filterAction.pending.payload === "offload" ? " as offloaded" : ""}. You can undo this later by changing the mark back.`}
      confirmLabel={filterAction.pending.payload === "offload" ? "Mark offloaded" : "Ignore matching"}
      busy={filterAction.busy}
      onConfirm={() => void filterAction.confirm()}
      onCancel={filterAction.cancel}
    />}
    </div>
  );
}

function Grid({ children, size }: { children: ReactNode; size: GallerySize }) {
  return <div className="grid" style={{ gap: "12px", gridTemplateColumns: autoFillColumns(size) }}>{children}</div>;
}

function DetailsDialog({ item, onClose, onPlay, onRetry, onIgnore }: { item: Item; onClose: () => void; onPlay: () => void; onRetry: () => void; onIgnore: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const resolution = item.media_width && item.media_height ? `${item.media_width} × ${item.media_height}` : "Not indexed";
  const rows = [
    ["Status", item.status], ["Type", item.kind], ["Favorited", item.favorited_at ?? "Unknown"],
    ["Duration", formatDuration(item.duration_s) ?? "Not indexed"], ["Resolution", resolution],
    ["Codec", item.media_codec ?? "Not indexed"], ["File size", formatSize(item.media_size) ?? "Not indexed"],
    ["Download attempts", String(item.attempt_count)], ["Last attempt", item.last_attempt_at ?? "Never"],
    ["Archive file", item.offloaded ? "Offloaded to external storage" : item.archive_missing ? "Missing (integrity scan)" : item.video_url ? "Ready" : "Not available"], ["Audio", audioStatus(item.has_audio, item.audio_silent)], ["Raw slideshow assets", item.has_assets ? "Available" : "None"],
  ];
  const safeLink = isSafeHttpUrl(item.link);
  return <Dialog labelledBy="favorite-details-title" onClose={onClose} initialFocusRef={closeRef} className="bg-black/70">
    <div className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-[var(--radius-media)] border border-line bg-surface p-5 shadow-2xl">
      <div className="flex items-start justify-between gap-4"><div><p className="tabular text-xs text-ink-faint">Favorite #{item.id}</p><h2 id="favorite-details-title" className="mt-1 text-lg font-semibold text-ink">Archive details</h2></div><button ref={closeRef} type="button" onClick={onClose} aria-label="Close details" className="rounded-[var(--radius-control)] p-2 text-ink-dim hover:bg-elevated hover:text-ink"><X size={18} /></button></div>
      {item.caption && <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-ink">{item.caption}</p>}
      {item.author && <p className="mt-2 text-sm text-ink-dim">Creator: {item.author}</p>}
      {item.song
        ? <p className="mt-2 text-sm text-ink-dim">Song: <a href={primarySongUrl(item.song)} target="_blank" rel="noreferrer" className="text-ink underline underline-offset-2 hover:text-active">{songLabel(item.song)}</a></p>
        : item.song_status === "no_match" ? <p className="mt-2 text-sm text-ink-faint">Song: not recognized</p>
        : item.song_status === "error" ? <p className="mt-2 text-sm text-ink-faint">Song: identification failed</p>
        : null}
      {item.error && <p className="mt-3 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">Last error: {item.error}</p>}
      <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-2">{rows.map(([label, value]) => <div key={label}><dt className="text-xs text-ink-faint">{label}</dt><dd className="mt-0.5 break-words text-sm text-ink">{value}</dd></div>)}</dl>
      <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4">
        {isFeedItem(item) && <button type="button" onClick={onPlay} className="inline-flex items-center gap-1.5 rounded-[var(--radius-control)] bg-accent px-3 py-2 text-sm font-medium text-on-accent"><Play size={15} weight="fill" /> Play this favorite</button>}
        {safeLink && <a href={item.link} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-[var(--radius-control)] border border-line px-3 py-2 text-sm text-ink-dim hover:text-ink"><LinkSimple size={15} className="mr-1.5" /> Open on TikTok</a>}
        {!isFeedItem(item) && item.status !== "ignored" && !item.offloaded && <button type="button" onClick={onRetry} className="inline-flex items-center rounded-[var(--radius-control)] border border-line px-3 py-2 text-sm text-ink-dim hover:text-ink">Retry download</button>}
        {(!isFeedItem(item) || item.status === "ignored") && <button type="button" onClick={onIgnore} className="inline-flex items-center rounded-[var(--radius-control)] border border-line px-3 py-2 text-sm text-ink-dim hover:text-ink">{item.status === "ignored" ? "Allow downloading" : "Don't download (mark unavailable)"}</button>}
      </div>
    </div>
  </Dialog>;
}

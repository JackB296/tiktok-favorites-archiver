import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  MagnifyingGlass,
  Play,
  ImageSquare,
  SlidersHorizontal,
  BookmarkSimple,
  Check,
  Trash,
  X,
  LinkSimple,
  Info,
  SpeakerSlash,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { MarkAction } from "../lib/api";
import type { GalleryPreset, GalleryPresetFilters, GalleryTermList, Item, PlaybackQueue, SearchSuggestions } from "../lib/types";
import { Button, ConfirmDialog, EmptyState, HelpLabel, Skeleton, cx, useDialogFocusTrap } from "../components/ui";
import { VirtualGalleryGrid } from "../components/VirtualGalleryGrid";
import { canLoadNextPage, autoFillColumns } from "../lib/virtualGrid";
import type { GallerySize } from "../lib/virtualGrid";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import { shouldLoadMore } from "../lib/galleryPaging.js";
import { readGalleryDetails } from "../lib/galleryPresentation.js";
import type { GalleryDetails } from "../lib/galleryPresentation.js";
import { audioStatus, readGallerySize } from "../lib/mediaPresentation.js";
import { primarySongUrl, songLabel } from "../lib/songLinks.js";
import { isFeedItem } from "../lib/feedItems";

const FILTERS = [
  { key: "", label: "All", help: "Show every favorite that matches the search and advanced filters." },
  { key: "video", label: "Videos", help: "Show favorites archived as ordinary video posts." },
  { key: "slideshow", label: "Slideshows", help: "Show photo posts rebuilt as playable slideshows, with original assets when available." },
];

const SIZE_LABELS: Record<GallerySize, string> = { s: "Small", m: "Medium", l: "Large", xl: "Extra large" };

type GalleryOrder = "latest" | "archive" | "size_desc" | "duration_desc" | "duration_asc" | "favorite_date_desc" | "favorite_date_asc" | "attempts_desc" | "last_attempt_desc" | "author_asc" | "audio_missing" | "random";

/** One shuffle per Random selection; the seed keeps cursor pages repeat-free. */
function newShuffleSeed() {
  return Math.floor(Math.random() * 2_147_483_647);
}

function filtersToSearchParams(filters: GalleryPresetFilters) {
  const params = new URLSearchParams();
  const values: Record<string, string | undefined> = {
    q: filters.search, kind: filters.kind, status: filters.status, sort: filters.order,
    min_duration: filters.minDuration, max_duration: filters.maxDuration,
    min_size: filters.minSize, max_size: filters.maxSize,
    min_width: filters.minWidth, max_width: filters.maxWidth,
    min_height: filters.minHeight, max_height: filters.maxHeight, codec: filters.codec,
    min_attempts: filters.minAttempts, max_attempts: filters.maxAttempts,
    recovery: filters.recovery ? "1" : undefined,
    from: filters.dateFrom, to: filters.dateTo, orientation: filters.orientation, assets: filters.assets, audio: filters.audio, offloaded: filters.offloaded, index: filters.indexState,
    include: filters.include, exclude: filters.exclude,
  };
  Object.entries(values).forEach(([key, value]) => { if (value && !(key === "sort" && value === "latest")) params.set(key, value); });
  return params;
}

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
  const fromUrl = (name: string) => searchParams.get(name) ?? "";
  const restoreRef = useRef<GalleryReturnState | null>(
    (location.state as { restore?: boolean } | null)?.restore && galleryReturnState && galleryReturnState.key === searchParams.toString()
      ? galleryReturnState
      : null,
  );
  const [search, setSearch] = useState(() => fromUrl("q"));
  const [suggestions, setSuggestions] = useState<SearchSuggestions | null>(null);
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [suggestActive, setSuggestActive] = useState(-1);
  const [kind, setKind] = useState(() => fromUrl("kind"));
  const [items, setItems] = useState<Item[] | null>(() => restoreRef.current?.items ?? null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);
  const initialLoadingPhase = useDelayedLoading(items === null);
  const [nextCursor, setNextCursor] = useState<number | null>(() => restoreRef.current?.nextCursor ?? null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreFailed, setLoadMoreFailed] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [status, setStatus] = useState(() => fromUrl("status"));
  const [order, setOrder] = useState<GalleryOrder>(() => (fromUrl("sort") as GalleryOrder) || "latest");
  const [randomSeed, setRandomSeed] = useState(newShuffleSeed);
  const [minDuration, setMinDuration] = useState(() => fromUrl("min_duration"));
  const [maxDuration, setMaxDuration] = useState(() => fromUrl("max_duration"));
  const [minSize, setMinSize] = useState(() => fromUrl("min_size"));
  const [maxSize, setMaxSize] = useState(() => fromUrl("max_size"));
  const [minWidth, setMinWidth] = useState(() => fromUrl("min_width"));
  const [maxWidth, setMaxWidth] = useState(() => fromUrl("max_width"));
  const [minHeight, setMinHeight] = useState(() => fromUrl("min_height"));
  const [maxHeight, setMaxHeight] = useState(() => fromUrl("max_height"));
  const [minAttempts, setMinAttempts] = useState(() => fromUrl("min_attempts"));
  const [maxAttempts, setMaxAttempts] = useState(() => fromUrl("max_attempts"));
  const [recovery, setRecovery] = useState(() => fromUrl("recovery") === "1");
  const [recoveryInboxBusy, setRecoveryInboxBusy] = useState(false);
  const [recoveryInboxMessage, setRecoveryInboxMessage] = useState<string | null>(null);
  const [codec, setCodec] = useState(() => fromUrl("codec"));
  const [dateFrom, setDateFrom] = useState(() => fromUrl("from"));
  const [dateTo, setDateTo] = useState(() => fromUrl("to"));
  const [orientation, setOrientation] = useState(() => fromUrl("orientation"));
  const [assets, setAssets] = useState(() => fromUrl("assets"));
  const [audio, setAudio] = useState(() => fromUrl("audio"));
  const [offloaded, setOffloaded] = useState(() => fromUrl("offloaded"));
  const [indexState, setIndexState] = useState(() => fromUrl("index"));
  const [include, setInclude] = useState(() => fromUrl("include"));
  const [exclude, setExclude] = useState(() => fromUrl("exclude"));
  const [presets, setPresets] = useState<GalleryPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [presetMessage, setPresetMessage] = useState<string | null>(null);
  const [termLists, setTermLists] = useState<GalleryTermList[]>([]);
  const [selectedTermListId, setSelectedTermListId] = useState("");
  const [termListName, setTermListName] = useState("");
  const [termListMode, setTermListMode] = useState<"include" | "exclude">("exclude");
  const [termListTerms, setTermListTerms] = useState("");
  const [termListMessage, setTermListMessage] = useState<string | null>(null);
  const [playbackQueues, setPlaybackQueues] = useState<PlaybackQueue[]>([]);
  const [selectedPlaybackQueueId, setSelectedPlaybackQueueId] = useState("");
  const [playbackQueueName, setPlaybackQueueName] = useState("");
  const [playbackQueueMessage, setPlaybackQueueMessage] = useState<string | null>(null);
  const [size, setSize] = useState<GallerySize>(() => readGallerySize(localStorage.getItem("gallery-size")));
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [cardDetails, setCardDetails] = useState<GalleryDetails>(() => readGalleryDetails(localStorage.getItem("gallery-card-details")));
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [filterActionBusy, setFilterActionBusy] = useState(false);
  const [filterActionMessage, setFilterActionMessage] = useState<string | null>(null);
  const [pendingFilterAction, setPendingFilterAction] = useState<{ action: "offload" | "ignore"; matched: number } | null>(null);
  const [inspectionMode, setInspectionMode] = useState(false);
  const [inspectedItem, setInspectedItem] = useState<Item | null>(null);

  function changeOrder(next: GalleryOrder) {
    if (next === "random") setRandomSeed(newShuffleSeed());
    setOrder(next);
  }

  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));

  const pageQuery = {
    search, kind, status, limit: 50, order,
    seed: order === "random" ? randomSeed : undefined,
    min_duration: num(minDuration),
    max_duration: num(maxDuration),
    min_size: minSize.trim() === "" ? undefined : Number(minSize) * 1024 * 1024,
    max_size: maxSize.trim() === "" ? undefined : Number(maxSize) * 1024 * 1024,
    min_width: num(minWidth),
    max_width: num(maxWidth),
    min_height: num(minHeight),
    max_height: num(maxHeight),
    min_attempts: num(minAttempts),
    max_attempts: num(maxAttempts),
    recovery: recovery || undefined,
    codec: codec || undefined,
    date_from: dateFrom || undefined,
    date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
    orientation: orientation || undefined,
    assets: (assets === "with" || assets === "without" ? assets : undefined) as "with" | "without" | undefined,
    audio: (audio === "with" || audio === "without" ? audio : undefined) as "with" | "without" | undefined,
    offloaded: (offloaded === "with" || offloaded === "without" ? offloaded : undefined) as "with" | "without" | undefined,
    index_state: (indexState === "indexed" || indexState === "missing" || indexState === "failed" ? indexState : undefined) as "indexed" | "missing" | "failed" | undefined,
    include, exclude,
  };

  const queryVersion = useRef(0);

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
      if (restoreRef.current.key === filtersToSearchParams(currentFilters()).toString()) return;
      restoreRef.current = null;
    }
    let alive = true;
    queryVersion.current += 1;
    setLoadError(null);
    setLoadMoreFailed(false);
    const t = window.setTimeout(() => {
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
    }, 200); // debounce typing
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [search, kind, status, order, randomSeed, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, audio, offloaded, indexState, include, exclude, reloadNonce]);

  useEffect(() => {
    setSelectedIds(new Set());
    setRecoveryMessage(null);
  }, [search, kind, status, order, randomSeed, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, audio, offloaded, indexState, include, exclude]);

  useEffect(() => {
    api.galleryPresets().then(setPresets).catch(() => setPresetMessage("Could not load saved filters."));
  }, []);

  useEffect(() => {
    api.galleryTermLists().then(setTermLists).catch(() => setTermListMessage("Could not load saved term lists."));
  }, []);

  useEffect(() => {
    api.playbackQueues().then(setPlaybackQueues).catch(() => setPlaybackQueueMessage("Could not load saved playback queues."));
  }, []);

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

  function currentFilters(): GalleryPresetFilters {
    return { search, kind, status, order, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, audio, offloaded, indexState, include, exclude };
  }

  useEffect(() => {
    // Only rewrite the URL when it's actually out of sync — a redundant replace()
    // would wipe navigation state (the Back-button `restore` flag) on mount.
    const next = filtersToSearchParams(currentFilters());
    if (next.toString() !== searchParams.toString()) setSearchParams(next, { replace: true });
  }, [search, kind, status, order, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, audio, offloaded, indexState, include, exclude, searchParams, setSearchParams]);

  function applyPreset(filters: GalleryPresetFilters) {
    setSearch(filters.search ?? "");
    setKind(filters.kind ?? "");
    setStatus(filters.status ?? "");
    changeOrder((filters.order as GalleryOrder) || "latest");
    setMinDuration(filters.minDuration ?? "");
    setMaxDuration(filters.maxDuration ?? "");
    setMinSize(filters.minSize ?? "");
    setMaxSize(filters.maxSize ?? "");
    setMinWidth(filters.minWidth ?? "");
    setMaxWidth(filters.maxWidth ?? "");
    setMinHeight(filters.minHeight ?? "");
    setMaxHeight(filters.maxHeight ?? "");
    setMinAttempts(filters.minAttempts ?? "");
    setMaxAttempts(filters.maxAttempts ?? "");
    setRecovery(Boolean(filters.recovery));
    setCodec(filters.codec ?? "");
    setDateFrom(filters.dateFrom ?? "");
    setDateTo(filters.dateTo ?? "");
    setOrientation(filters.orientation ?? "");
    setAssets(filters.assets ?? "");
    setAudio(filters.audio ?? "");
    setOffloaded(filters.offloaded ?? "");
    setIndexState(filters.indexState ?? "");
    setInclude(filters.include ?? "");
    setExclude(filters.exclude ?? "");
  }

  async function savePreset() {
    if (!presetName.trim()) return;
    try {
      const saved = await api.createGalleryPreset(presetName.trim(), currentFilters());
      setPresets((current) => [...current, saved].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedPresetId(String(saved.id));
      setPresetName("");
      setPresetMessage("Saved.");
    } catch (error) {
      setPresetMessage((error as Error).message);
    }
  }

  async function deletePreset() {
    const id = Number(selectedPresetId);
    if (!id) return;
    try {
      await api.deleteGalleryPreset(id);
      setPresets((current) => current.filter((preset) => preset.id !== id));
      setSelectedPresetId("");
      setPresetMessage("Deleted.");
    } catch (error) {
      setPresetMessage((error as Error).message);
    }
  }

  function parsedTerms(value: string) {
    return Array.from(new Set(value.split(",").map((term) => term.trim()).filter(Boolean)));
  }

  function applyTermList() {
    const list = termLists.find((item) => item.id === Number(selectedTermListId));
    if (!list) return;
    const merged = Array.from(new Set([...parsedTerms(list.mode === "include" ? include : exclude), ...list.terms]));
    if (list.mode === "include") setInclude(merged.join(", "));
    else setExclude(merged.join(", "));
    setTermListMessage(`${list.name} applied.`);
  }

  async function saveTermList() {
    const terms = parsedTerms(termListTerms);
    if (!termListName.trim() || !terms.length) return;
    try {
      const saved = await api.createGalleryTermList(termListName.trim(), termListMode, terms);
      setTermLists((current) => [...current, saved].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedTermListId(String(saved.id));
      setTermListName("");
      setTermListTerms("");
      setTermListMessage("Saved.");
    } catch (error) {
      setTermListMessage((error as Error).message);
    }
  }

  async function deleteTermList() {
    const id = Number(selectedTermListId);
    if (!id) return;
    try {
      await api.deleteGalleryTermList(id);
      setTermLists((current) => current.filter((list) => list.id !== id));
      setSelectedTermListId("");
      setTermListMessage("Deleted.");
    } catch (error) {
      setTermListMessage((error as Error).message);
    }
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

  function changeCardDetail(key: keyof GalleryDetails, shown: boolean) {
    setCardDetails((current) => {
      const next = { ...current, [key]: shown };
      localStorage.setItem("gallery-card-details", JSON.stringify(next));
      return next;
    });
  }

  function clearAllFilters() {
    setSearch(""); setKind(""); setStatus(""); setOrder("latest");
    setMinDuration(""); setMaxDuration(""); setMinSize(""); setMaxSize("");
    setMinWidth(""); setMaxWidth(""); setMinHeight(""); setMaxHeight(""); setCodec("");
    setMinAttempts(""); setMaxAttempts("");
    setRecovery(false); setRecoveryInboxMessage(null);
    setDateFrom(""); setDateTo(""); setOrientation(""); setAssets(""); setAudio(""); setOffloaded(""); setIndexState(""); setInclude(""); setExclude("");
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
    const itemIds = Array.from(selectedIds);
    if (!playbackQueueName.trim() || !itemIds.length) return;
    try {
      const saved = await api.createPlaybackQueue(playbackQueueName.trim(), itemIds);
      setPlaybackQueues((current) => [...current, saved].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedPlaybackQueueId(String(saved.id));
      setPlaybackQueueName("");
      setPlaybackQueueMessage("Saved.");
    } catch (error) {
      setPlaybackQueueMessage((error as Error).message);
    }
  }

  function playSavedQueue() {
    const queue = playbackQueues.find((item) => item.id === Number(selectedPlaybackQueueId));
    if (queue) navigate(`/?queue=${queue.item_ids.join(",")}`);
  }

  async function deletePlaybackQueue() {
    const id = Number(selectedPlaybackQueueId);
    if (!id) return;
    try {
      await api.deletePlaybackQueue(id);
      setPlaybackQueues((current) => current.filter((queue) => queue.id !== id));
      setSelectedPlaybackQueueId("");
      setPlaybackQueueMessage("Deleted.");
    } catch (error) {
      setPlaybackQueueMessage((error as Error).message);
    }
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
      const result = await api.markItems(action, { ids });
      const page = await api.itemPage(pageQuery);
      queryVersion.current += 1;
      setItems(page.items);
      setNextCursor(page.next_cursor);
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
    await api.requeueItems([id]).catch(() => {});
    setInspectedItem(null);
    restoreRef.current = null; // force a fresh page so the change shows
    setReloadNonce((n) => n + 1);
  }

  async function ignoreItem(id: number, ignored: boolean) {
    await api.markItems(ignored ? "unignore" : "ignore", { ids: [id] }).catch(() => {});
    setInspectedItem(null);
    restoreRef.current = null;
    setReloadNonce((n) => n + 1);
  }

  /** Open a favorite in the Feed. With an active search/filter, scope the Feed to
      the whole matching set in the current sort order; otherwise open the archive. */
  function openInFeed(itemId: number) {
    const params = new URLSearchParams(currentFilterSelector());
    if (order !== "latest") params.set("order", order);
    if (order === "random") params.set("seed", String(randomSeed));
    const from = filtersToSearchParams(currentFilters()).toString();
    // Snapshot this view so the Feed's Back button restores it at the same scroll spot.
    galleryReturnState = { key: from, items: items ?? [], nextCursor, scrollTop: scrollRef.current?.scrollTop ?? 0 };
    params.set("from", from);
    params.set("item", String(itemId));
    navigate(`/?${params.toString()}`);
  }

  /** The current page filters as the same key/value strings `api.itemPage` sends. */
  function currentFilterSelector(): Record<string, string> {
    const excluded = new Set(["order", "seed", "limit", "cursor"]);
    const filter: Record<string, string> = {};
    Object.entries(pageQuery).forEach(([key, value]) => {
      if (excluded.has(key) || value == null || value === "") return;
      filter[key] = String(value);
    });
    return filter;
  }

  async function markMatching(action: "offload" | "ignore") {
    if (filterActionBusy) return;
    setFilterActionBusy(true);
    setFilterActionMessage(null);
    try {
      const preview = await api.markItems(action, { filter: currentFilterSelector() }, true);
      if (!preview.matched) {
        setFilterActionMessage("No favorites match the current filters.");
        return;
      }
      setPendingFilterAction({ action, matched: preview.matched });
    } catch (error) {
      setFilterActionMessage((error as Error).message);
    } finally {
      setFilterActionBusy(false);
    }
  }

  async function confirmMarkMatching() {
    if (!pendingFilterAction || filterActionBusy) return;
    setFilterActionBusy(true);
    try {
      const result = await api.markItems(pendingFilterAction.action, { filter: currentFilterSelector() });
      const page = await api.itemPage(pageQuery);
      queryVersion.current += 1;
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setFilterActionMessage(`${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.`);
    } catch (error) {
      setFilterActionMessage((error as Error).message);
    } finally {
      setPendingFilterAction(null);
      setFilterActionBusy(false);
    }
  }

  async function toggleRecoveryInbox() {
    if (recovery) {
      setRecovery(false);
      setRecoveryInboxMessage(null);
      return;
    }
    setRecoveryInboxBusy(true);
    setRecoveryInboxMessage(null);
    try {
      await api.verify();
      setRecovery(true);
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

  const activeFilters: Array<{ label: string; clear: () => void }> = [];
  const addFilter = (value: string, label: string, clear: () => void) => value && activeFilters.push({ label, clear });
  addFilter(search, `Search: ${search}`, () => setSearch(""));
  addFilter(kind, kind === "video" ? "Videos" : "Slideshows", () => setKind(""));
  addFilter(status, `Status: ${status}`, () => setStatus(""));
  if (order !== "latest") activeFilters.push({ label: `Sort: ${order.replace(/_/g, " ")}`, clear: () => setOrder("latest") });
  addFilter(minDuration, `≥ ${minDuration}s`, () => setMinDuration("")); addFilter(maxDuration, `≤ ${maxDuration}s`, () => setMaxDuration(""));
  addFilter(minSize, `≥ ${minSize} MB`, () => setMinSize("")); addFilter(maxSize, `≤ ${maxSize} MB`, () => setMaxSize(""));
  addFilter(minWidth, `width ≥ ${minWidth}`, () => setMinWidth("")); addFilter(maxWidth, `width ≤ ${maxWidth}`, () => setMaxWidth(""));
  addFilter(minHeight, `height ≥ ${minHeight}`, () => setMinHeight("")); addFilter(maxHeight, `height ≤ ${maxHeight}`, () => setMaxHeight(""));
  addFilter(minAttempts, `≥ ${minAttempts} attempts`, () => setMinAttempts("")); addFilter(maxAttempts, `≤ ${maxAttempts} attempts`, () => setMaxAttempts(""));
  if (recovery) activeFilters.push({ label: "Recovery inbox", clear: () => setRecovery(false) });
  addFilter(codec, `Codec: ${codec}`, () => setCodec("")); addFilter(dateFrom, `After: ${dateFrom}`, () => setDateFrom("")); addFilter(dateTo, `Before: ${dateTo}`, () => setDateTo(""));
  addFilter(orientation, orientation, () => setOrientation("")); addFilter(assets, assets === "with" ? "Has raw assets" : "No raw assets", () => setAssets("")); addFilter(audio, audio === "with" ? "Has audio" : "No audio", () => setAudio("")); addFilter(offloaded, offloaded === "with" ? "Offloaded" : "Stored locally", () => setOffloaded("")); addFilter(indexState, `Index: ${indexState}`, () => setIndexState("")); addFilter(include, `Include: ${include}`, () => setInclude("")); addFilter(exclude, `Exclude: ${exclude}`, () => setExclude(""));

  const suggestItems = suggestions
    ? [
        ...suggestions.creators.map((c) => ({ value: c.value, kind: "Creator" })),
        ...suggestions.hashtags.map((h) => ({ value: h.value, kind: "Hashtag" })),
        ...suggestions.terms.map((t) => ({ value: t.value, kind: "Keyword" })),
      ]
    : [];
  const showSuggest = suggestOpen && suggestItems.length > 0;
  function pickSuggestion(value: string) {
    setSearch(value);
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
            onChange={(e) => setSearch(e.target.value)}
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
              onClick={() => setKind(f.key)}
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
        <Button size="xs" onClick={requeueSelected} disabled={!selectedIds.size || recoveryBusy}>{recoveryBusy ? "Queuing…" : "Queue selected for Sync"}</Button>
        <span className="text-xs text-ink-faint">Only failed favorites and finished favorites missing their file will be queued.</span>
        {recoveryMessage && <span className="w-full text-xs text-ink-dim">{recoveryMessage}</span>}
        {playbackQueueMessage && <span className="w-full text-xs text-ink-dim">{playbackQueueMessage}</span>}
      </section>}

      {inspectionMode && <p className="mb-5 rounded-[var(--radius-control)] border border-line bg-surface px-3 py-2.5 text-sm text-ink-dim">Inspect mode: choose a thumbnail to view its full archive metadata. Click the <Info size={13} className="inline" /> button again to return to playback clicks.</p>}

      {activeFilters.length > 0 && <div className="mb-5 flex flex-wrap items-center gap-2" aria-label="Active Gallery filters">
        <span className="text-xs text-ink-faint">Active filters</span>
        {activeFilters.map((filter) => <button key={filter.label} type="button" onClick={() => { filter.clear(); setSelectedPresetId(""); }} className="inline-flex items-center gap-1 rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-dim hover:text-ink">{filter.label}<X size={12} aria-hidden="true" /></button>)}
        <button type="button" onClick={clearAllFilters} className="px-1 text-xs text-ink-dim underline underline-offset-2 hover:text-ink">Clear all</button>
        <button type="button" onClick={copyFilteredLink} className="inline-flex items-center gap-1 px-1 text-xs text-ink-dim underline underline-offset-2 hover:text-ink"><LinkSimple size={13} /> Copy link</button>
      </div>}

      {advanced && <section className="mb-5 grid gap-4 rounded-[var(--radius-media)] border border-line bg-surface p-4">
        <div>
          <p className="text-xs font-semibold text-ink">Saved filters</p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="Applies a named snapshot of every current Gallery search, filter, and sort setting.">Saved filters</HelpLabel>
              <select value={selectedPresetId} onChange={(e) => { const preset = presets.find((item) => item.id === Number(e.target.value)); setSelectedPresetId(e.target.value); if (preset) applyPreset(preset.filters); }} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Apply a saved filter…</option>{presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select>
            </label>
            <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="Names and saves the complete filter setup currently shown, including whitelist and blacklist terms.">Save current filters as</HelpLabel>
              <input value={presetName} onChange={(e) => setPresetName(e.target.value)} maxLength={80} placeholder="e.g. Games without fyp" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
            </label>
            <Button variant="ghost" size="sm" onClick={savePreset} disabled={!presetName.trim()}><BookmarkSimple size={15} /> Save</Button>
            {selectedPresetId && <Button variant="danger" size="sm" onClick={deletePreset}><Trash size={15} /> Delete</Button>}
            {presetMessage && <span className="text-xs text-ink-faint">{presetMessage}</span>}
          </div>
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
            <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-4"><Button variant="ghost" size="sm" onClick={applyTermList} disabled={!selectedTermListId}>Apply selected list</Button>{selectedTermListId && <Button variant="danger" size="sm" onClick={deleteTermList}><Trash size={15} /> Delete</Button>}<Button variant="ghost" size="sm" onClick={saveTermList} disabled={!termListName.trim() || !parsedTerms(termListTerms).length}><BookmarkSimple size={15} /> Save new list</Button>{termListMessage && <span className="text-xs text-ink-faint">{termListMessage}</span>}</div>
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Playback queues</p>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="A saved ordered selection of up to 100 favorites that can be reopened in Feed later.">Saved playback queues</HelpLabel>
              <select value={selectedPlaybackQueueId} onChange={(e) => setSelectedPlaybackQueueId(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Choose a queue…</option>{playbackQueues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name} · {queue.item_ids.length} favorites</option>)}</select>
            </label>
            <Button variant="ghost" size="sm" onClick={playSavedQueue} disabled={!selectedPlaybackQueueId}><Play size={15} weight="fill" /> Play queue</Button>
            {selectedPlaybackQueueId && <Button variant="danger" size="sm" onClick={deletePlaybackQueue}><Trash size={15} /> Delete</Button>}
            {playbackQueueMessage && <span className="text-xs text-ink-faint">{playbackQueueMessage}</span>}
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Sort &amp; status</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-dim"><HelpLabel help="Controls the order of matching favorites. Random creates a fresh temporary shuffle each time it is selected.">Sort order</HelpLabel>
              <select value={order} onChange={(e) => changeOrder(e.target.value as GalleryOrder)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="latest">Latest imported favorite</option><option value="archive">Oldest imported favorite</option><option value="favorite_date_desc">Newest favorite date</option><option value="favorite_date_asc">Oldest favorite date</option><option value="author_asc">Creator A-Z</option><option value="audio_missing">Missing audio first</option><option value="size_desc">Largest file</option><option value="duration_desc">Longest video</option><option value="duration_asc">Shortest video</option><option value="attempts_desc">Most download attempts</option><option value="last_attempt_desc">Most recently attempted</option><option value="random">Random order</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Ready has local media. Failed can be retried. Unavailable means TikTok reports the original is gone and it will not be retried automatically.">Archive status</HelpLabel>
              <select value={status} onChange={(e) => setStatus(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any status</option><option value="done">Ready</option><option value="pending">Pending</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="expired">Unavailable original</option><option value="ignored">Ignored</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Shows favorites Sync has tried at least this many times, including successful and failed attempts.">Minimum download attempts</HelpLabel>
              <input value={minAttempts} onChange={(e) => setMinAttempts(e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Shows favorites Sync has tried no more than this many times. Use 0 to find pending favorites never attempted.">Maximum download attempts</HelpLabel>
              <input value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Media facts</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-dim"><HelpLabel help="Filters indexed media by its frame shape: taller than wide, wider than tall, or equal width and height.">Orientation</HelpLabel>
              <select value={orientation} onChange={(e) => setOrientation(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any orientation</option><option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="square">Square</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Filters photo posts by whether their original downloaded images and audio are still stored beside the rebuilt video.">Raw slideshow assets</HelpLabel>
              <select value={assets} onChange={(e) => setAssets(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any asset state</option><option value="with">Has original assets</option><option value="without">No original assets</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Filters videos by whether the archived file has an audio stream. 'No audio' shows silent videos — whether the original had no sound or the audio never came through.">Audio</HelpLabel>
              <select value={audio} onChange={(e) => setAudio(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any audio</option><option value="with">Has audio</option><option value="without">No audio</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Offloaded favorites are archived on external storage (like a NAS), so they have no local file here but are not missing.">External storage</HelpLabel>
              <select value={offloaded} onChange={(e) => setOffloaded(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any</option><option value="with">Offloaded</option><option value="without">Local</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Indexed favorites have a thumbnail and media facts. Missing has not been indexed yet. Failed means thumbnail or media inspection failed.">Gallery index health</HelpLabel>
              <select value={indexState} onChange={(e) => setIndexState(e.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any index state</option><option value="indexed">Indexed</option><option value="missing">Not indexed</option><option value="failed">Index failed</option></select>
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps videos at least this many seconds long.">Minimum duration (seconds)</HelpLabel>
              <input value={minDuration} onChange={(e) => setMinDuration(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps videos no longer than this many seconds.">Maximum duration (seconds)</HelpLabel>
              <input value={maxDuration} onChange={(e) => setMaxDuration(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps local video files at least this large.">Minimum file size (MB)</HelpLabel>
              <input value={minSize} onChange={(e) => setMinSize(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps local video files no larger than this value.">Maximum file size (MB)</HelpLabel>
              <input value={maxSize} onChange={(e) => setMaxSize(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and filters by the encoded video frame width in pixels.">Minimum width (px)</HelpLabel>
              <input value={minWidth} onChange={(e) => setMinWidth(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and excludes frames wider than this pixel value.">Maximum width (px)</HelpLabel>
              <input value={maxWidth} onChange={(e) => setMaxWidth(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and filters by the encoded video frame height in pixels.">Minimum height (px)</HelpLabel>
              <input value={minHeight} onChange={(e) => setMinHeight(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and excludes frames taller than this pixel value.">Maximum height (px)</HelpLabel>
              <input value={maxHeight} onChange={(e) => setMaxHeight(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and matches encoded video formats such as h264, hevc, or vp9. Separate alternatives with commas.">Video codec</HelpLabel>
              <input value={codec} onChange={(e) => setCodec(e.target.value)} placeholder="e.g. h264, hevc" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
            </label>
          </div>
        </div>
        <div className="border-t border-line pt-3">
          <p className="text-xs font-semibold text-ink">Dates &amp; terms</p>
          <div className="mt-2 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <label className="text-xs text-ink-dim"><HelpLabel help="Uses the date recorded in your TikTok export and excludes favorites saved before this day.">Favorited on or after</HelpLabel>
              <input value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} type="date" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Uses the date recorded in your TikTok export and excludes favorites saved after this day.">Favorited on or before</HelpLabel>
              <input value={dateTo} onChange={(e) => setDateTo(e.target.value)} type="date" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
            </label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Whitelist: every comma-separated term must match the caption or creator. Use this to keep only specific creators, hashtags, or topics.">Whitelist creators / tags / words</HelpLabel><input value={include} onChange={(e) => setInclude(e.target.value)} placeholder="e.g. @creator, #games" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" /></label>
            <label className="text-xs text-ink-dim"><HelpLabel help="Blacklist: any matching comma-separated term removes that favorite. Use this to hide creators, hashtags, or topics such as #fyp.">Blacklist creators / tags / words</HelpLabel><input value={exclude} onChange={(e) => setExclude(e.target.value)} placeholder="e.g. #fyp, spoilers" className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" /></label>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="text-xs text-ink-dim"><HelpLabel help="Applies an archive mark to every favorite matching the current search and filters. A count is shown for confirmation before anything changes.">With these filters…</HelpLabel></span>
          <Button variant="ghost" size="sm" onClick={() => markMatching("offload")} disabled={filterActionBusy}>Mark all matching offloaded</Button>
          <Button variant="ghost" size="sm" onClick={() => markMatching("ignore")} disabled={filterActionBusy}>Ignore all matching</Button>
          {filterActionMessage && <span className="text-xs text-ink-faint">{filterActionMessage}</span>}
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
            renderItem={(it, cardWidth) => <Thumb key={it.id} item={it} cardWidth={cardWidth} details={cardDetails} selecting={selectionMode} inspecting={inspectionMode} selected={selectedIds.has(it.id)} onClick={() => selectionMode ? toggleSelection(it.id) : inspectionMode || !isFeedItem(it) ? setInspectedItem(it) : openInFeed(it.id)} />}
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
    {pendingFilterAction && <ConfirmDialog
      title={pendingFilterAction.action === "offload" ? "Mark matching favorites offloaded?" : "Ignore matching favorites?"}
      message={`This will ${pendingFilterAction.action === "offload" ? "mark" : "ignore"} ${pendingFilterAction.matched} favorite${pendingFilterAction.matched === 1 ? "" : "s"}${pendingFilterAction.action === "offload" ? " as offloaded" : ""}. You can undo this later by changing the mark back.`}
      confirmLabel={pendingFilterAction.action === "offload" ? "Mark offloaded" : "Ignore matching"}
      busy={filterActionBusy}
      onConfirm={() => void confirmMarkMatching()}
      onCancel={() => { setPendingFilterAction(null); setFilterActionMessage("Cancelled."); }}
    />}
    </div>
  );
}

function Grid({ children, size }: { children: ReactNode; size: GallerySize }) {
  return <div className="grid" style={{ gap: "12px", gridTemplateColumns: autoFillColumns(size) }}>{children}</div>;
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return null;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return minutes ? `${minutes}:${String(total % 60).padStart(2, "0")}` : `${total}s`;
}

function formatSize(bytes: number | null) {
  if (bytes == null) return null;
  return bytes >= 1_000_000_000 ? `${(bytes / 1_000_000_000).toFixed(1)} GB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
}

function Thumb({ item, details, cardWidth, onClick, selecting = false, inspecting = false, selected = false }: { item: Item; details: GalleryDetails; cardWidth: number; onClick: () => void; selecting?: boolean; inspecting?: boolean; selected?: boolean }) {
  const duration = formatDuration(item.duration_s);
  const resolution = item.media_width && item.media_height ? `${item.media_width}×${item.media_height}` : null;
  const size = formatSize(item.media_size);
  // Card sets its own font size from its measured width, so every em-based badge,
  // caption, and icon below scales with the chosen thumbnail size (floored so text
  // stays legible on the smallest step, capped so it never dominates the largest).
  const fontSize = `${Math.min(26, Math.max(9, Math.round(cardWidth * 0.062)))}px`;
  return (
    <button
      onClick={onClick}
      style={{ fontSize }}
      aria-label={`${selecting ? selected ? "Unselect" : "Select" : inspecting ? "Inspect" : "Play"} favorite #${item.id}${item.caption ? `: ${item.caption}` : ""}`}
      aria-pressed={selecting ? selected : undefined}
      className={cx("group relative aspect-[9/16] overflow-hidden rounded-[var(--radius-media)] bg-black text-left", selected && "ring-2 ring-accent ring-offset-2 ring-offset-canvas")}
    >
      {item.thumbnail_url ? (
        <img
          src={item.thumbnail_url}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : item.images[0] ? (
        <img
          src={item.images[0]}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : (
        <div className="tabular flex h-full w-full items-center justify-center text-[1.1em] text-ink-faint">#{item.id}</div>
      )}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
      {details.archiveNumber && <span className="tabular absolute left-[0.55em] top-[0.55em] rounded bg-black/50 px-[0.4em] py-[0.15em] text-[0.78em] text-white/80">
        #{item.id}
      </span>}
      {(item.has_audio === false || item.audio_silent === true) && <span title="No sound — no audio stream, or a stream that is silent. You can replace the file from its Feed settings." className="absolute left-[0.55em] top-[2.5em] inline-flex items-center gap-[0.3em] rounded bg-bad/90 px-[0.4em] py-[0.15em] text-[0.78em] font-semibold text-white"><SpeakerSlash size="1em" weight="fill" />{audioStatus(item.has_audio, item.audio_silent)}</span>}
      {selecting && <span aria-hidden="true" className={cx("absolute right-[0.55em] top-[0.55em] flex h-[1.5em] w-[1.5em] items-center justify-center rounded-full border", selected ? "border-accent bg-accent text-on-accent" : "border-white/70 bg-black/50 text-white/80")}>{selected ? <Check size="1em" weight="bold" /> : null}</span>}
      {inspecting && <span aria-hidden="true" className="absolute right-[0.55em] top-[0.55em] flex h-[1.5em] w-[1.5em] items-center justify-center rounded-full border border-white/70 bg-black/50 text-white/80"><Info size="1em" /></span>}
      <div className={cx("absolute top-[0.55em] flex max-w-[65%] flex-col items-end gap-[0.3em] text-[0.78em] text-white/85", selecting || inspecting ? "right-[2.5em]" : "right-[0.55em]")}>
        {((details.duration && duration) || (details.resolution && resolution)) && <span className="rounded bg-black/50 px-[0.4em] py-[0.15em]">{[details.duration ? duration : null, details.resolution ? resolution : null].filter(Boolean).join(" · ")}</span>}
        {!selecting && !inspecting && <span className="rounded-full bg-black/40 p-[0.35em] opacity-0 transition group-hover:opacity-100"><Play size="1em" weight="fill" /></span>}
      </div>
      <div className="absolute inset-x-0 bottom-0 p-[0.7em]">
        {item.status === "failed" && <p title={item.error ?? undefined} className="truncate text-[0.78em] font-medium text-bad">{item.error ?? "Download failed"}</p>}
        {item.status === "expired" && <p title="TikTok no longer serves the original link. Its archive number is preserved and Sync will not retry it automatically." className="truncate text-[0.78em] font-medium text-white/60">Original unavailable</p>}
        {item.status === "ignored" && <p title="Marked as don't-download. Its archive number is preserved and Sync will not attempt it." className="truncate text-[0.78em] font-medium text-white/60">Not downloading</p>}
        {item.offloaded && <span title="Archived on external storage, so it is not flagged as missing here." className="mb-[0.3em] inline-block rounded bg-black/50 px-[0.4em] py-[0.15em] text-[0.78em] font-medium text-white/80">offloaded</span>}
        {details.author && item.author && <p className="truncate text-[0.85em] font-medium text-white">{item.author}</p>}
        {details.caption && item.caption && <p className="truncate text-[0.78em] text-white/70">{item.caption}</p>}
        {details.technical && (item.media_codec || size) && <p className="mt-[0.15em] truncate text-[0.78em] text-white/70 opacity-0 transition group-hover:opacity-100">{[item.media_codec, size].filter(Boolean).join(" · ")}</p>}
      </div>
    </button>
  );
}

function DetailsDialog({ item, onClose, onPlay, onRetry, onIgnore }: { item: Item; onClose: () => void; onPlay: () => void; onRetry: () => void; onIgnore: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  useDialogFocusTrap(panelRef);
  useEffect(() => {
    closeRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);
  const resolution = item.media_width && item.media_height ? `${item.media_width} × ${item.media_height}` : "Not indexed";
  const rows = [
    ["Status", item.status], ["Type", item.kind], ["Favorited", item.favorited_at ?? "Unknown"],
    ["Duration", formatDuration(item.duration_s) ?? "Not indexed"], ["Resolution", resolution],
    ["Codec", item.media_codec ?? "Not indexed"], ["File size", formatSize(item.media_size) ?? "Not indexed"],
    ["Download attempts", String(item.attempt_count)], ["Last attempt", item.last_attempt_at ?? "Never"],
    ["Archive file", item.offloaded ? "Offloaded to external storage" : item.archive_missing ? "Missing (integrity scan)" : item.video_url ? "Ready" : "Not available"], ["Audio", audioStatus(item.has_audio, item.audio_silent)], ["Raw slideshow assets", item.has_assets ? "Available" : "None"],
  ];
  const safeLink = /^https?:\/\//i.test(item.link);
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="favorite-details-title">
    <div ref={panelRef} className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-[var(--radius-media)] border border-line bg-surface p-5 shadow-2xl">
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
  </div>;
}

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  MagnifyingGlass,
  Play,
  ImageSquare,
  SlidersHorizontal,
  BookmarkSimple,
  Trash,
  X,
  LinkSimple,
  SquaresFour,
  Info,
  SpeakerSlash,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { MarkAction } from "../lib/api";
import type { GalleryPreset, GalleryPresetFilters, GalleryTermList, Item, PlaybackQueue } from "../lib/types";
import { EmptyState, HelpLabel, Skeleton, cx } from "../components/ui";
import { VirtualGalleryGrid } from "../components/VirtualGalleryGrid";
import { canLoadNextPage } from "../lib/virtualGrid";
import { useDelayedLoading } from "../lib/useDelayedLoading";
import { shouldLoadMore } from "../lib/galleryPaging.js";
import { readGalleryDetails } from "../lib/galleryPresentation.js";
import type { GalleryDetails } from "../lib/galleryPresentation.js";
import { audioStatus, readGalleryDensity } from "../lib/mediaPresentation.js";

const FILTERS = [
  { key: "", label: "All", help: "Show every favorite that matches the search and advanced filters." },
  { key: "video", label: "Videos", help: "Show favorites archived as ordinary video posts." },
  { key: "slideshow", label: "Slideshows", help: "Show photo posts rebuilt as playable slideshows, with original assets when available." },
];

type GalleryDensity = "compact" | "comfortable";

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
    from: filters.dateFrom, to: filters.dateTo, orientation: filters.orientation, assets: filters.assets, offloaded: filters.offloaded, index: filters.indexState,
    include: filters.include, exclude: filters.exclude,
  };
  Object.entries(values).forEach(([key, value]) => { if (value && !(key === "sort" && value === "latest")) params.set(key, value); });
  return params;
}

export function Gallery() {
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const loadMoreRef = useRef<() => void>(() => {});
  const loadingMoreRef = useRef(false);
  const [searchParams, setSearchParams] = useSearchParams();
  const fromUrl = (name: string) => searchParams.get(name) ?? "";
  const [search, setSearch] = useState(() => fromUrl("q"));
  const [kind, setKind] = useState(() => fromUrl("kind"));
  const [items, setItems] = useState<Item[] | null>(null);
  const initialLoadingPhase = useDelayedLoading(items === null);
  const [nextCursor, setNextCursor] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
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
  const [density, setDensity] = useState<GalleryDensity>(() => readGalleryDensity(localStorage.getItem("gallery-density")));
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [cardDetails, setCardDetails] = useState<GalleryDetails>(() => readGalleryDetails(localStorage.getItem("gallery-card-details")));
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [recoveryMessage, setRecoveryMessage] = useState<string | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [filterActionBusy, setFilterActionBusy] = useState(false);
  const [filterActionMessage, setFilterActionMessage] = useState<string | null>(null);
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
    offloaded: (offloaded === "with" || offloaded === "without" ? offloaded : undefined) as "with" | "without" | undefined,
    index_state: (indexState === "indexed" || indexState === "missing" || indexState === "failed" ? indexState : undefined) as "indexed" | "missing" | "failed" | undefined,
    include, exclude,
  };

  const queryVersion = useRef(0);

  useEffect(() => {
    let alive = true;
    queryVersion.current += 1;
    const t = window.setTimeout(() => {
      api
        .itemPage(pageQuery)
        .then((page) => {
          if (!alive) return;
          setItems(page.items);
          setNextCursor(page.next_cursor);
        })
        .catch(() => alive && setItems([]));
    }, 200); // debounce typing
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [search, kind, status, order, randomSeed, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, offloaded, indexState, include, exclude]);

  useEffect(() => {
    setSelectedIds(new Set());
    setRecoveryMessage(null);
  }, [search, kind, status, order, randomSeed, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, offloaded, indexState, include, exclude]);

  useEffect(() => {
    api.galleryPresets().then(setPresets).catch(() => setPresetMessage("Could not load saved filters."));
  }, []);

  useEffect(() => {
    api.galleryTermLists().then(setTermLists).catch(() => setTermListMessage("Could not load saved term lists."));
  }, []);

  useEffect(() => {
    api.playbackQueues().then(setPlaybackQueues).catch(() => setPlaybackQueueMessage("Could not load saved playback queues."));
  }, []);

  function currentFilters(): GalleryPresetFilters {
    return { search, kind, status, order, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, offloaded, indexState, include, exclude };
  }

  useEffect(() => {
    setSearchParams(filtersToSearchParams(currentFilters()), { replace: true });
  }, [search, kind, status, order, minDuration, maxDuration, minSize, maxSize, minWidth, maxWidth, minHeight, maxHeight, minAttempts, maxAttempts, recovery, codec, dateFrom, dateTo, orientation, assets, offloaded, indexState, include, exclude, setSearchParams]);

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

  function changeDensity(next: GalleryDensity) {
    setDensity(next);
    localStorage.setItem("gallery-density", next);
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
    setDateFrom(""); setDateTo(""); setOrientation(""); setAssets(""); setOffloaded(""); setIndexState(""); setInclude(""); setExclude("");
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
      setRecoveryMessage(`${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.`);
    } catch (error) {
      setRecoveryMessage((error as Error).message);
    } finally {
      setRecoveryBusy(false);
    }
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
      const filter = currentFilterSelector();
      const preview = await api.markItems(action, { filter }, true);
      if (!preview.matched) {
        setFilterActionMessage("No favorites match the current filters.");
        return;
      }
      const verb = action === "offload" ? "mark" : "ignore";
      if (!window.confirm(`This will ${verb} ${preview.matched} favorite${preview.matched === 1 ? "" : "s"}${action === "offload" ? " as offloaded" : ""} — proceed?`)) {
        setFilterActionMessage("Cancelled.");
        return;
      }
      const result = await api.markItems(action, { filter });
      const page = await api.itemPage(pageQuery);
      queryVersion.current += 1;
      setItems(page.items);
      setNextCursor(page.next_cursor);
      setFilterActionMessage(`${result.changed} favorite${result.changed === 1 ? "" : "s"} updated.`);
    } catch (error) {
      setFilterActionMessage((error as Error).message);
    } finally {
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
  addFilter(orientation, orientation, () => setOrientation("")); addFilter(assets, assets === "with" ? "Has raw assets" : "No raw assets", () => setAssets("")); addFilter(offloaded, offloaded === "with" ? "Offloaded" : "Stored locally", () => setOffloaded("")); addFilter(indexState, `Index: ${indexState}`, () => setIndexState("")); addFilter(include, `Include: ${include}`, () => setInclude("")); addFilter(exclude, `Exclude: ${exclude}`, () => setExclude(""));

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
    <div className="mx-auto max-w-[1400px] px-4 py-6">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search caption, hashtag, author"
            title="Searches indexed captions, hashtags, creator names, and source links. Best text matches appear first unless an advanced sort is selected."
            className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
          />
          {search.trim() && <p className="mt-1 text-xs text-ink-faint">Best matches first. Choose an advanced sort to override relevance.</p>}
        </div>
        <div className="flex flex-wrap gap-1.5 sm:justify-end">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setKind(f.key)}
              title={f.help}
              className={cx(
                "rounded-full px-3 py-1.5 text-xs font-medium transition",
                kind === f.key ? "bg-accent text-on-accent" : "border border-line text-ink-dim hover:text-ink",
              )}
            >
              {f.label}
            </button>
          ))}
          <button onClick={() => changeDensity(density === "compact" ? "comfortable" : "compact")} title={density === "compact" ? "Compact thumbnails (switch to comfortable)" : "Comfortable thumbnails (switch to compact)"} aria-label={density === "compact" ? "Use comfortable thumbnail density" : "Use compact thumbnail density"} aria-pressed={density === "compact"} className={cx("rounded-full border p-1.5 transition", density === "compact" ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}><SquaresFour size={16} /></button>
          <button onClick={() => setDetailsOpen((value) => !value)} aria-expanded={detailsOpen} className={cx("rounded-full border px-3 py-1.5 text-xs font-medium transition", detailsOpen ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>Card details</button>
          <button onClick={() => selectionMode ? leaveSelectionMode() : enterSelectionMode()} aria-pressed={selectionMode} className={cx("rounded-full border px-3 py-1.5 text-xs font-medium transition", selectionMode ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>{selectionMode ? "Done selecting" : "Select"}</button>
          <button onClick={toggleRecoveryInbox} disabled={recoveryInboxBusy} aria-pressed={recovery} className={cx("rounded-full border px-3 py-1.5 text-xs font-medium transition disabled:opacity-40", recovery ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")}>{recoveryInboxBusy ? "Checking…" : recovery ? "Recovery inbox" : "Recovery"}</button>
          <button onClick={() => { if (inspectionMode) { setInspectionMode(false); setInspectedItem(null); } else { leaveSelectionMode(); setInspectionMode(true); } }} aria-pressed={inspectionMode} className={cx("rounded-full border p-1.5 transition", inspectionMode ? "border-accent bg-accent text-on-accent" : "border-line text-ink-dim hover:text-ink")} aria-label={inspectionMode ? "Leave inspect mode" : "Inspect Gallery metadata"}><Info size={16} /></button>
          <button onClick={() => setAdvanced((value) => !value)} title="Open saved filters, whitelist and blacklist lists, playback queues, and detailed archive filters." aria-label="Toggle advanced filters" className="rounded-full border border-line p-1.5 text-ink-dim hover:text-ink"><SlidersHorizontal size={16} /></button>
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
        <button type="button" onClick={playSelected} disabled={!selectedIds.size || recoveryBusy} className="rounded border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-elevated disabled:opacity-40"><Play size={14} weight="fill" /> Play selection</button>
        <input value={playbackQueueName} onChange={(event) => setPlaybackQueueName(event.target.value)} maxLength={80} placeholder="Save as queue…" className="h-8 rounded border border-line bg-elevated px-2 text-xs text-ink placeholder:text-ink-faint" />
        <button type="button" onClick={savePlaybackQueue} disabled={!selectedIds.size || !playbackQueueName.trim() || recoveryBusy} className="rounded border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-elevated disabled:opacity-40"><BookmarkSimple size={14} /> Save queue</button>
        <button type="button" onClick={() => markSelected(allSelectedOffloaded ? "unoffload" : "offload")} disabled={!selectedIds.size || recoveryBusy} title="Offloaded favorites are archived on external storage, so Sync and integrity checks stop flagging them as missing." className="rounded border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-elevated disabled:opacity-40">{allSelectedOffloaded ? "Unmark offloaded" : "Mark offloaded"}</button>
        <button type="button" onClick={() => markSelected(allSelectedIgnored ? "unignore" : "ignore")} disabled={!selectedIds.size || recoveryBusy} title="Ignored favorites keep their place in the archive but Sync never downloads them." className="rounded border border-line px-3 py-1.5 text-xs font-medium text-ink hover:bg-elevated disabled:opacity-40">{allSelectedIgnored ? "Allow downloading" : "Don't download"}</button>
        <button type="button" onClick={requeueSelected} disabled={!selectedIds.size || recoveryBusy} className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-on-accent disabled:opacity-40">{recoveryBusy ? "Queuing…" : "Queue selected for Sync"}</button>
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

      {advanced && <section className="mb-5 grid gap-3 rounded-[var(--radius-media)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-3">
        <div className="flex flex-wrap items-end gap-2 sm:col-span-2 lg:col-span-3">
          <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="Applies a named snapshot of every current Gallery search, filter, and sort setting.">Saved filters</HelpLabel>
            <select value={selectedPresetId} onChange={(e) => { const preset = presets.find((item) => item.id === Number(e.target.value)); setSelectedPresetId(e.target.value); if (preset) applyPreset(preset.filters); }} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Apply a saved filter…</option>{presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select>
          </label>
          <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="Names and saves the complete filter setup currently shown, including whitelist and blacklist terms.">Save current filters as</HelpLabel>
            <input value={presetName} onChange={(e) => setPresetName(e.target.value)} maxLength={80} placeholder="e.g. Games without fyp" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
          </label>
          <button type="button" onClick={savePreset} disabled={!presetName.trim()} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40"><BookmarkSimple size={15} /> Save</button>
          {selectedPresetId && <button type="button" onClick={deletePreset} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-bad"><Trash size={15} /> Delete</button>}
          {presetMessage && <span className="text-xs text-ink-faint">{presetMessage}</span>}
        </div>
        <div className="grid gap-3 border-t border-line pt-3 sm:col-span-2 sm:grid-cols-2 lg:col-span-3 lg:grid-cols-4">
          <label className="text-xs text-ink-dim sm:col-span-2"><HelpLabel help="Reusable groups of creators, hashtags, or words. Applying a list adds its terms to the matching whitelist or blacklist field.">Saved creator / tag lists</HelpLabel>
            <select value={selectedTermListId} onChange={(e) => setSelectedTermListId(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Choose a list…</option>{termLists.map((list) => <option key={list.id} value={list.id}>{list.name} · {list.mode === "include" ? "whitelist" : "blacklist"}</option>)}</select>
          </label>
          <label className="text-xs text-ink-dim"><HelpLabel help="A descriptive name for this reusable group of whitelist or blacklist terms.">List name</HelpLabel>
            <input value={termListName} onChange={(e) => setTermListName(e.target.value)} maxLength={80} placeholder="e.g. No FYP" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
          </label>
          <label className="text-xs text-ink-dim"><HelpLabel help="Whitelist keeps only favorites matching every applied whitelist group. Blacklist removes favorites matching any applied blacklist term. You can save and use both kinds together.">List behavior</HelpLabel>
            <select value={termListMode} onChange={(e) => setTermListMode(e.target.value as "include" | "exclude")} className="mt-1 h-9 rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="exclude">Blacklist</option><option value="include">Whitelist</option></select>
          </label>
          <label className="text-xs text-ink-dim sm:col-span-2 lg:col-span-4"><HelpLabel help="Creators, hashtags, or words separated by commas. Hashtags may be entered with or without the # symbol.">Creators, tags, or words</HelpLabel>
            <input value={termListTerms} onChange={(e) => setTermListTerms(e.target.value)} placeholder="#fyp, foryou" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
          </label>
          <div className="flex flex-wrap items-center gap-2 sm:col-span-2 lg:col-span-4"><button type="button" onClick={applyTermList} disabled={!selectedTermListId} className="inline-flex h-9 items-center rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40">Apply selected list</button>{selectedTermListId && <button type="button" onClick={deleteTermList} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-bad"><Trash size={15} /> Delete</button>}<button type="button" onClick={saveTermList} disabled={!termListName.trim() || !parsedTerms(termListTerms).length} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40"><BookmarkSimple size={15} /> Save new list</button>{termListMessage && <span className="text-xs text-ink-faint">{termListMessage}</span>}</div>
        </div>
        <div className="flex flex-wrap items-end gap-2 border-t border-line pt-3 sm:col-span-2 lg:col-span-3">
          <label className="min-w-48 flex-1 text-xs text-ink-dim"><HelpLabel help="A saved ordered selection of up to 100 favorites that can be reopened in Feed later.">Saved playback queues</HelpLabel>
            <select value={selectedPlaybackQueueId} onChange={(e) => setSelectedPlaybackQueueId(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Choose a queue…</option>{playbackQueues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name} · {queue.item_ids.length} favorites</option>)}</select>
          </label>
          <button type="button" onClick={playSavedQueue} disabled={!selectedPlaybackQueueId} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40"><Play size={15} weight="fill" /> Play queue</button>
          {selectedPlaybackQueueId && <button type="button" onClick={deletePlaybackQueue} className="inline-flex h-9 items-center gap-1 rounded border border-line px-3 text-sm text-ink-dim hover:text-bad"><Trash size={15} /> Delete</button>}
          {playbackQueueMessage && <span className="text-xs text-ink-faint">{playbackQueueMessage}</span>}
        </div>
        <label className="text-xs text-ink-dim"><HelpLabel help="Controls the order of matching favorites. Random creates a fresh temporary shuffle each time it is selected.">Sort order</HelpLabel>
          <select value={order} onChange={(e) => changeOrder(e.target.value as GalleryOrder)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="latest">Latest imported favorite</option><option value="archive">Oldest imported favorite</option><option value="favorite_date_desc">Newest favorite date</option><option value="favorite_date_asc">Oldest favorite date</option><option value="author_asc">Creator A–Z</option><option value="audio_missing">Missing audio first</option><option value="size_desc">Largest file</option><option value="duration_desc">Longest video</option><option value="duration_asc">Shortest video</option><option value="attempts_desc">Most download attempts</option><option value="last_attempt_desc">Most recently attempted</option><option value="random">Random order</option></select>
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Ready has local media. Failed can be retried. Unavailable means TikTok reports the original is gone and it will not be retried automatically.">Archive status</HelpLabel>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any status</option><option value="done">Ready</option><option value="pending">Pending</option><option value="failed">Failed</option><option value="skipped">Skipped</option><option value="expired">Unavailable original</option><option value="ignored">Ignored</option></select>
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Shows favorites Sync has tried at least this many times, including successful and failed attempts.">Minimum download attempts</HelpLabel>
          <input value={minAttempts} onChange={(e) => setMinAttempts(e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Shows favorites Sync has tried no more than this many times. Use 0 to find pending favorites never attempted.">Maximum download attempts</HelpLabel>
          <input value={maxAttempts} onChange={(e) => setMaxAttempts(e.target.value)} type="number" min="0" step="1" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Filters indexed media by its frame shape: taller than wide, wider than tall, or equal width and height.">Orientation</HelpLabel>
          <select value={orientation} onChange={(e) => setOrientation(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any orientation</option><option value="portrait">Portrait</option><option value="landscape">Landscape</option><option value="square">Square</option></select>
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Filters photo posts by whether their original downloaded images and audio are still stored beside the rebuilt video.">Raw slideshow assets</HelpLabel>
          <select value={assets} onChange={(e) => setAssets(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any asset state</option><option value="with">Has original assets</option><option value="without">No original assets</option></select>
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Offloaded favorites are archived on external storage (like a NAS), so they have no local file here but are not missing.">External storage</HelpLabel>
          <select value={offloaded} onChange={(e) => setOffloaded(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any</option><option value="with">Offloaded</option><option value="without">Local</option></select>
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Indexed favorites have a thumbnail and media facts. Missing has not been indexed yet. Failed means thumbnail or media inspection failed.">Gallery index health</HelpLabel>
          <select value={indexState} onChange={(e) => setIndexState(e.target.value)} className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink"><option value="">Any index state</option><option value="indexed">Indexed</option><option value="missing">Not indexed</option><option value="failed">Index failed</option></select>
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps videos at least this many seconds long.">Minimum duration (seconds)</HelpLabel>
          <input value={minDuration} onChange={(e) => setMinDuration(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps videos no longer than this many seconds.">Maximum duration (seconds)</HelpLabel>
          <input value={maxDuration} onChange={(e) => setMaxDuration(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps local video files at least this large.">Minimum file size (MB)</HelpLabel>
          <input value={minSize} onChange={(e) => setMinSize(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and keeps local video files no larger than this value.">Maximum file size (MB)</HelpLabel>
          <input value={maxSize} onChange={(e) => setMaxSize(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and filters by the encoded video frame width in pixels.">Minimum width (px)</HelpLabel>
          <input value={minWidth} onChange={(e) => setMinWidth(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and excludes frames wider than this pixel value.">Maximum width (px)</HelpLabel>
          <input value={maxWidth} onChange={(e) => setMaxWidth(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and filters by the encoded video frame height in pixels.">Minimum height (px)</HelpLabel>
          <input value={minHeight} onChange={(e) => setMinHeight(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and excludes frames taller than this pixel value.">Maximum height (px)</HelpLabel>
          <input value={maxHeight} onChange={(e) => setMaxHeight(e.target.value)} type="number" min="0" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Requires indexed media and matches encoded video formats such as h264, hevc, or vp9. Separate alternatives with commas.">Video codec</HelpLabel>
          <input value={codec} onChange={(e) => setCodec(e.target.value)} placeholder="e.g. h264, hevc" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Uses the date recorded in your TikTok export and excludes favorites saved before this day.">Favorited on or after</HelpLabel>
          <input value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} type="date" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Uses the date recorded in your TikTok export and excludes favorites saved after this day.">Favorited on or before</HelpLabel>
          <input value={dateTo} onChange={(e) => setDateTo(e.target.value)} type="date" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink" />
        </label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Whitelist: every comma-separated term must match the caption or creator. Use this to keep only specific creators, hashtags, or topics.">Whitelist creators / tags / words</HelpLabel><input value={include} onChange={(e) => setInclude(e.target.value)} placeholder="e.g. @creator, #games" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" /></label>
        <label className="text-xs text-ink-dim"><HelpLabel help="Blacklist: any matching comma-separated term removes that favorite. Use this to hide creators, hashtags, or topics such as #fyp.">Blacklist creators / tags / words</HelpLabel><input value={exclude} onChange={(e) => setExclude(e.target.value)} placeholder="e.g. #fyp, spoilers" className="mt-1 h-9 w-full rounded border border-line bg-elevated px-2 text-sm text-ink placeholder:text-ink-faint" /></label>
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3 sm:col-span-2 lg:col-span-3">
          <span className="text-xs text-ink-dim"><HelpLabel help="Applies an archive mark to every favorite matching the current search and filters. A count is shown for confirmation before anything changes.">With these filters…</HelpLabel></span>
          <button type="button" onClick={() => markMatching("offload")} disabled={filterActionBusy} className="inline-flex h-9 items-center rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40">Mark all matching offloaded</button>
          <button type="button" onClick={() => markMatching("ignore")} disabled={filterActionBusy} className="inline-flex h-9 items-center rounded border border-line px-3 text-sm text-ink-dim hover:text-ink disabled:opacity-40">Ignore all matching</button>
          {filterActionMessage && <span className="text-xs text-ink-faint">{filterActionMessage}</span>}
        </div>
      </section>}

      {!items && initialLoadingPhase === "quiet" ? (
        <div className="min-h-40" aria-busy="true" aria-label="Loading Gallery" />
      ) : initialLoadingPhase === "indicator" ? (
        <Grid density={density}>
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[9/16] !rounded-[var(--radius-media)]" />
          ))}
        </Grid>
      ) : !items ? (
        <div className="min-h-40" aria-busy="true" aria-label="Loading Gallery" />
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
            density={density}
            scrollRef={scrollRef}
            renderItem={(it) => <Thumb key={it.id} item={it} details={cardDetails} selecting={selectionMode} inspecting={inspectionMode} selected={selectedIds.has(it.id)} onClick={() => selectionMode ? toggleSelection(it.id) : inspectionMode ? setInspectedItem(it) : navigate(`/?item=${it.id}`)} />}
          />
          {nextCursor != null && (
            <div className="mt-6 flex items-center justify-center gap-2 py-3 text-xs text-ink-faint" aria-live="polite" aria-busy={loadingMore}>
              <span aria-hidden="true" className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line border-t-accent" />
              <span>{loadingMore ? "Loading more favorites…" : "More favorites load as you scroll."}</span>
            </div>
          )}
        </>
      )}
    </div>
    {inspectedItem && <DetailsDialog item={inspectedItem} onClose={() => setInspectedItem(null)} onPlay={() => navigate(`/?item=${inspectedItem.id}`)} />}
    </div>
  );
}

function Grid({ children, density }: { children: ReactNode; density: GalleryDensity }) {
  return <div className={cx("grid", density === "compact" ? "grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 xl:grid-cols-10" : "grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5")}>{children}</div>;
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

function Thumb({ item, details, onClick, selecting = false, inspecting = false, selected = false }: { item: Item; details: GalleryDetails; onClick: () => void; selecting?: boolean; inspecting?: boolean; selected?: boolean }) {
  const duration = formatDuration(item.duration_s);
  const resolution = item.media_width && item.media_height ? `${item.media_width}×${item.media_height}` : null;
  const size = formatSize(item.media_size);
  return (
    <button
      onClick={onClick}
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
        <div className="tabular flex h-full w-full items-center justify-center text-ink-faint">#{item.id}</div>
      )}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
      {details.archiveNumber && <span className="tabular absolute left-2 top-2 rounded bg-black/50 px-1.5 py-0.5 text-[10px] text-white/80">
        #{item.id}
      </span>}
      {item.has_audio === false && <span title="FFprobe found no audio stream. You can replace this file from its Feed settings." className="absolute left-2 top-9 inline-flex items-center gap-1 rounded bg-bad/90 px-1.5 py-0.5 text-[10px] font-semibold text-white"><SpeakerSlash size={11} weight="fill" />{audioStatus(item.has_audio)}</span>}
      {selecting && <span aria-hidden="true" className={cx("absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full border text-xs", selected ? "border-accent bg-accent text-on-accent" : "border-white/70 bg-black/50 text-white/80")}>{selected ? "✓" : ""}</span>}
      {inspecting && <span aria-hidden="true" className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full border border-white/70 bg-black/50 text-xs text-white/80"><Info size={12} /></span>}
      <div className={cx("absolute top-2 flex max-w-[65%] flex-col items-end gap-1 text-[10px] text-white/85", selecting || inspecting ? "right-9" : "right-2")}>
        {((details.duration && duration) || (details.resolution && resolution)) && <span className="rounded bg-black/50 px-1.5 py-0.5">{[details.duration ? duration : null, details.resolution ? resolution : null].filter(Boolean).join(" · ")}</span>}
        {!selecting && !inspecting && <span className="rounded-full bg-black/40 p-1 opacity-0 transition group-hover:opacity-100"><Play size={12} weight="fill" /></span>}
      </div>
      <div className="absolute inset-x-0 bottom-0 p-2.5">
        {item.status === "failed" && <p title={item.error ?? undefined} className="truncate text-[11px] font-medium text-bad">{item.error ?? "Download failed"}</p>}
        {item.status === "expired" && <p title="TikTok no longer serves the original link. Its archive number is preserved and Sync will not retry it automatically." className="truncate text-[11px] font-medium text-white/60">Original unavailable</p>}
        {item.status === "ignored" && <p title="Marked as don't-download. Its archive number is preserved and Sync will not attempt it." className="truncate text-[11px] font-medium text-white/60">Not downloading</p>}
        {item.offloaded && <span title="Archived on external storage, so it is not flagged as missing here." className="mb-1 inline-block rounded bg-black/50 px-1.5 py-0.5 text-[10px] font-medium text-white/80">offloaded</span>}
        {details.author && item.author && <p className="truncate text-xs font-medium text-white">{item.author}</p>}
        {details.caption && item.caption && <p className="truncate text-[11px] text-white/70">{item.caption}</p>}
        {details.technical && (item.media_codec || size) && <p className="mt-0.5 truncate text-[10px] text-white/55 opacity-0 transition group-hover:opacity-100">{[item.media_codec, size].filter(Boolean).join(" · ")}</p>}
      </div>
    </button>
  );
}

function DetailsDialog({ item, onClose, onPlay }: { item: Item; onClose: () => void; onPlay: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
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
    ["Archive file", item.offloaded ? "Offloaded to external storage" : item.archive_missing ? "Missing (integrity scan)" : item.video_url ? "Ready" : "Not available"], ["Audio", audioStatus(item.has_audio)], ["Raw slideshow assets", item.has_assets ? "Available" : "None"],
  ];
  const safeLink = /^https?:\/\//i.test(item.link);
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-labelledby="favorite-details-title">
    <div className="max-h-[90dvh] w-full max-w-xl overflow-y-auto rounded-[var(--radius-media)] border border-line bg-surface p-5 shadow-2xl">
      <div className="flex items-start justify-between gap-4"><div><p className="tabular text-xs text-ink-faint">Favorite #{item.id}</p><h2 id="favorite-details-title" className="mt-1 text-lg font-semibold text-ink">Archive details</h2></div><button ref={closeRef} type="button" onClick={onClose} aria-label="Close details" className="rounded-[var(--radius-control)] p-2 text-ink-dim hover:bg-elevated hover:text-ink"><X size={18} /></button></div>
      {item.caption && <p className="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-ink">{item.caption}</p>}
      {item.author && <p className="mt-2 text-sm text-ink-dim">Creator: {item.author}</p>}
      {item.error && <p className="mt-3 rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">Last error: {item.error}</p>}
      <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 border-t border-line pt-4 sm:grid-cols-2">{rows.map(([label, value]) => <div key={label}><dt className="text-xs text-ink-faint">{label}</dt><dd className="mt-0.5 break-words text-sm text-ink">{value}</dd></div>)}</dl>
      <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4"><button type="button" onClick={onPlay} className="inline-flex items-center gap-1.5 rounded-[var(--radius-control)] bg-accent px-3 py-2 text-sm font-medium text-on-accent"><Play size={15} weight="fill" /> Play this favorite</button>{safeLink && <a href={item.link} target="_blank" rel="noreferrer" className="inline-flex items-center rounded-[var(--radius-control)] border border-line px-3 py-2 text-sm text-ink-dim hover:text-ink">Open TikTok</a>}</div>
    </div>
  </div>;
}

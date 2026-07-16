import { feedTrimPlan } from "./viewerFeed.js";

/** Minimum shape the window machine needs from a feed entry. */
export type FeedItemLike = { id: number };

export type FeedSourceKind = "latest" | "queue" | "filtered" | "random";

/**
 * Pure state machine for the Viewer's feed window.
 *
 * Every feed mode is "an ordered id list plus a loaded window over it":
 * filtered, random, and queue feeds know their full id order up front, while
 * the latest feed discovers ids through a cursor stream. The machine owns the
 * invariants the four modes share:
 *
 * - one generation guards every async completion — a source switch bumps it,
 *   so completions that raced across the switch return the SAME state
 *   reference and callers skip their side effects;
 * - below and above loads are each exclusive with themselves but may coexist,
 *   because they mutate disjoint state (idEnd/append vs idStart/prepend);
 * - trimming reuses feedTrimPlan so the visible Favorite keeps its scroll
 *   position when items far behind it are dropped.
 *
 * Everything here is synchronous and side-effect free; useFeedWindow wires the
 * machine to fetches and the DOM.
 */
export type FeedWindowState<T extends FeedItemLike> = {
  /** Source epoch. Completions carrying an older generation are discarded. */
  generation: number;
  /** Full known id order (list sources); empty for cursor streams. */
  ids: number[];
  /** Id-index of the window's first requested id. Lowered only by completeLoadAbove. */
  idStart: number;
  /** Id-index one past the window's last requested id. Raised only by beginLoadBelow. */
  idEnd: number;
  /** Next-page cursor for stream sources; null when exhausted or unused. */
  cursor: number | null;
  /** The loaded window (requested ids minus unplayable entries). */
  items: T[];
  loadingBelow: boolean;
  loadingAbove: boolean;
};

/** Fields a source's initial load installs into the machine. */
export type FeedWindowInit<T extends FeedItemLike> = {
  items: T[];
  ids?: number[];
  idStart?: number;
  /** Defaults to ids.length (a fully requested list, like a curated queue). */
  idEnd?: number;
  cursor?: number | null;
};

/** A source's initial window plus presentation directives for the hook. */
export type FeedInit<T extends FeedItemLike> = FeedWindowInit<T> & {
  activeId: number | null;
  /** List total for badges (shuffle length, filter match count, queue ready count). */
  total?: number | null;
  /** "target" scrolls to activeId before paint; "top" scrolls to 0 after paint. */
  scrollTo?: "top" | "target";
};

export type FeedBatch<T extends FeedItemLike> = { items: T[]; cursor?: number | null };

/** A prepared below fetch: how many ids it consumes and how to run it. */
export type BelowPlan<T extends FeedItemLike> = { consumeIds: number; fetch: () => Promise<FeedBatch<T>> };

/** A prepared above fetch: the idStart it will establish and how to run it. */
export type AbovePlan<T extends FeedItemLike> = { idStart: number; fetch: () => Promise<T[]> };

/**
 * One feed mode. `key` is identity — the hook switches sources (new generation)
 * whenever it changes. loadInitial resolving null means "keep the current feed",
 * used by imperative sources so a failed shuffle or resume leaves the previous
 * feed usable.
 */
export interface FeedSource<T extends FeedItemLike> {
  key: string;
  kind: FeedSourceKind;
  loadInitial(): Promise<FeedInit<T> | null>;
  /** Plan the next batch below the window; null when exhausted. */
  loadBelow?(state: FeedWindowState<T>): BelowPlan<T> | null;
  /** Plan the batch above the window; null at the top. */
  loadAbove?(state: FeedWindowState<T>): AbovePlan<T> | null;
}

export function createFeedWindow<T extends FeedItemLike>(): FeedWindowState<T> {
  return { generation: 0, ids: [], idStart: 0, idEnd: 0, cursor: null, items: [], loadingBelow: false, loadingAbove: false };
}

/**
 * A new source takes over: bump the generation (stranding every in-flight
 * completion) and cancel pending loads. The window itself is kept so a source
 * whose initial load fails softly can leave the previous feed usable.
 */
export function switchSource<T extends FeedItemLike>(state: FeedWindowState<T>): FeedWindowState<T> {
  return { ...state, generation: state.generation + 1, loadingBelow: false, loadingAbove: false };
}

/** Install a source's initial window. No-op when `generation` is stale. */
export function setInitial<T extends FeedItemLike>(state: FeedWindowState<T>, generation: number, init: FeedWindowInit<T>): FeedWindowState<T> {
  if (generation !== state.generation) return state;
  const ids = init.ids ?? [];
  return {
    ...state,
    ids,
    idStart: init.idStart ?? 0,
    idEnd: init.idEnd ?? ids.length,
    cursor: init.cursor ?? null,
    items: init.items,
    loadingBelow: false,
    loadingAbove: false,
  };
}

/** Drop the window entirely (a source's initial load failed hard). */
export function clearWindow<T extends FeedItemLike>(state: FeedWindowState<T>): FeedWindowState<T> {
  return { ...state, ids: [], idStart: 0, idEnd: 0, cursor: null, items: [], loadingBelow: false, loadingAbove: false };
}

/** The next unrequested id slice below the window. */
export function belowIdSlice<T extends FeedItemLike>(state: FeedWindowState<T>, batchSize: number): number[] {
  return state.ids.slice(state.idEnd, state.idEnd + batchSize);
}

/** The id slice directly above the window, or null at the top of the list. */
export function aboveIdSlice<T extends FeedItemLike>(state: FeedWindowState<T>, batchSize: number): { start: number; ids: number[] } | null {
  const end = state.idStart;
  const start = Math.max(0, end - batchSize);
  if (start >= end) return null;
  return { start, ids: state.ids.slice(start, end) };
}

/**
 * Claim the below slot. Refuses (returns null) while a below load is pending.
 * `consumeIds` advances idEnd immediately — like the original loaders, a slice
 * whose fetch later fails is skipped rather than retried, so the feed always
 * progresses.
 */
export function beginLoadBelow<T extends FeedItemLike>(state: FeedWindowState<T>, consumeIds: number): FeedWindowState<T> | null {
  if (state.loadingBelow) return null;
  return { ...state, loadingBelow: true, idEnd: state.idEnd + consumeIds };
}

/** Append a below batch. Returns the SAME state when `generation` is stale. */
export function completeLoadBelow<T extends FeedItemLike>(state: FeedWindowState<T>, generation: number, items: T[], cursor?: number | null): FeedWindowState<T> {
  if (generation !== state.generation) return state;
  return { ...state, items: [...state.items, ...items], cursor: cursor === undefined ? state.cursor : cursor, loadingBelow: false };
}

export function failLoadBelow<T extends FeedItemLike>(state: FeedWindowState<T>, generation: number): FeedWindowState<T> {
  if (generation !== state.generation) return state;
  return { ...state, loadingBelow: false };
}

/** Claim the above slot. Refuses while pending. idStart moves only on completion. */
export function beginLoadAbove<T extends FeedItemLike>(state: FeedWindowState<T>): FeedWindowState<T> | null {
  if (state.loadingAbove) return null;
  return { ...state, loadingAbove: true };
}

/** Prepend an above batch and lower idStart. Returns the SAME state when stale. */
export function completeLoadAbove<T extends FeedItemLike>(state: FeedWindowState<T>, generation: number, items: T[], idStart: number): FeedWindowState<T> {
  if (generation !== state.generation) return state;
  return { ...state, items: [...items, ...state.items], idStart, loadingAbove: false };
}

export function failLoadAbove<T extends FeedItemLike>(state: FeedWindowState<T>, generation: number): FeedWindowState<T> {
  if (generation !== state.generation) return state;
  return { ...state, loadingAbove: false };
}

/**
 * Drop items far behind the active one (feedTrimPlan decides how many) and plan
 * the scrollTop that keeps the visible Favorite in place. Returns the SAME
 * state when nothing needs trimming. idStart/idEnd stay untouched: the hook
 * only trims forward-only sources (latest, random) — filtered and queue feeds
 * keep their windows — and neither of those loads above.
 */
export function trimWindow<T extends FeedItemLike>(
  state: FeedWindowState<T>,
  activeIndex: number,
  scrollTop: number,
  viewportHeight: number,
  keepBehind: number,
): { state: FeedWindowState<T>; plan: { removeCount: number; restoredScrollTop: number } } {
  const plan = feedTrimPlan(activeIndex, scrollTop, viewportHeight, keepBehind);
  if (plan.removeCount <= 0) return { state, plan };
  return { state: { ...state, items: state.items.slice(plan.removeCount) }, plan };
}

/** How far to move scrollTop after prepending so the view holds still. */
export function prependScrollAdjustment(prependedCount: number, viewportHeight: number): number {
  return prependedCount * viewportHeight;
}

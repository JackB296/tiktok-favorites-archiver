import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Dispatch, RefObject, SetStateAction } from "react";
import type { Item } from "./types";
import {
  beginLoadAbove,
  beginLoadBelow,
  clearWindow,
  completeLoadAbove,
  completeLoadBelow,
  createFeedWindow,
  failLoadAbove,
  failLoadBelow,
  prependScrollAdjustment,
  setInitial,
  switchSource,
  trimWindow,
} from "./feedWindow";
import type { FeedSource, FeedSourceKind, FeedWindowState } from "./feedWindow";
import { activeFeedIndex, nextWheelTargetIndex, shouldCommitWheelTarget } from "./viewerFeed.js";

const KEEP_BEHIND = 5;

export type FeedWindow = {
  /** Loaded window; null until the very first source finishes (or fails) loading. */
  items: Item[] | null;
  error: string | null;
  activeId: number | null;
  setActiveId: Dispatch<SetStateAction<number | null>>;
  /** The wheel gesture's requested snap target while its smooth scroll animates. */
  transitionTargetId: number | null;
  /** Kind of the source whose window is currently live. */
  kind: FeedSourceKind;
  /** Kind of a source whose initial load is still in flight, else null. */
  switchingTo: FeedSourceKind | null;
  /** Source-reported list total (shuffle length, filter match count, queue ready count). */
  total: number | null;
  /** Optional source display name. */
  label: string | null;
  /** Position of the active item in the source's full id order, when known. */
  activePosition: number | null;
  updateItem: (item: Item) => void;
};

/**
 * Owns the feed window for the Viewer: one source at a time, one generation
 * guard for every async completion, pagination in both directions, bounded
 * trimming, and the scroll bookkeeping that keeps the visible Favorite still
 * across prepends and trims. All policy lives in the pure machine
 * (lib/feedWindow.ts); this hook only wires it to fetches and the DOM.
 */
export function useFeedWindow(source: FeedSource<Item>, containerRef: RefObject<HTMLDivElement>): FeedWindow {
  const machine = useRef<FeedWindowState<Item>>(createFeedWindow<Item>());
  /** The source whose window is live. Pagination pauses while a switch is in
      flight (initPending) and resumes against this source if the switch keeps
      the current feed (loadInitial resolving null). */
  const liveSource = useRef<FeedSource<Item> | null>(null);
  const initPending = useRef(false);
  const positions = useRef<Map<number, number> | null>(null);
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [transitionTargetId, setTransitionTargetId] = useState<number | null>(null);
  const [kind, setKind] = useState<FeedSourceKind>(source.kind);
  const [switchingTo, setSwitchingTo] = useState<FeedSourceKind | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const [label, setLabel] = useState<string | null>(null);
  const [belowRetryTick, setBelowRetryTick] = useState(0);
  const pendingScrollToId = useRef<number | null>(null);
  const pendingPrepend = useRef(0);
  const pendingTrim = useRef<{ removeCount: number; restoredScrollTop: number } | null>(null);
  const pendingWheelTargetId = useRef<number | null>(null);
  const wheelGestureReady = useRef(true);
  const wheelIdleTimer = useRef<number | null>(null);
  const wheelSettleTimer = useRef<number | null>(null);
  const belowRetryTimer = useRef<number | null>(null);
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;
  const sourceRef = useRef(source);
  sourceRef.current = source;

  const cancelWheelTarget = useCallback(() => {
    if (wheelSettleTimer.current != null) window.clearTimeout(wheelSettleTimer.current);
    wheelSettleTimer.current = null;
    pendingWheelTargetId.current = null;
    setTransitionTargetId(null);
  }, []);

  // Switching sources bumps the machine generation, which strands every
  // in-flight completion (initial, below, above) from the previous source.
  // The old window stays live until the new source's initial load lands.
  useEffect(() => {
    let alive = true;
    const src = sourceRef.current;
    machine.current = switchSource(machine.current);
    const generation = machine.current.generation;
    initPending.current = true;
    setSwitchingTo(src.kind);
    setError(null);
    src.loadInitial()
      .then((init) => {
        if (!alive || generation !== machine.current.generation) return; // superseded by a newer source
        initPending.current = false;
        setSwitchingTo(null);
        if (!init) return; // the source chose to keep the current feed (e.g. shuffle failed)
        machine.current = setInitial(machine.current, generation, init);
        liveSource.current = src;
        positions.current = init.ids?.length ? new Map(init.ids.map((id, index) => [id, index])) : null;
        cancelWheelTarget(); // the old feed's snap target has no meaning in the new window
        setItems(machine.current.items);
        setActiveId(init.activeId);
        setKind(src.kind);
        setTotal(init.total ?? null);
        setLabel(init.label ?? null);
        if (init.scrollTo === "target" && init.activeId != null) {
          pendingScrollToId.current = init.activeId; // scroll the feed to the clicked item before paint
        } else if (init.scrollTo === "top") {
          requestAnimationFrame(() => containerRef.current?.scrollTo({ top: 0 }));
        }
      })
      .catch((err: unknown) => {
        if (!alive || generation !== machine.current.generation) return;
        initPending.current = false;
        setSwitchingTo(null);
        machine.current = clearWindow(machine.current);
        liveSource.current = src;
        positions.current = null;
        setItems([]);
        setError((err as Error).message || "Request failed");
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source.key]);

  // Track which card sits at the snap point; a pending wheel target takes over
  // until its smooth scroll is effectively at its destination.
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  // Wheel gestures advance exactly one card per gesture, from the latest
  // requested snap target rather than the animation's stale visible card.
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  useEffect(() => () => {
    if (wheelIdleTimer.current != null) window.clearTimeout(wheelIdleTimer.current);
    if (wheelSettleTimer.current != null) window.clearTimeout(wheelSettleTimer.current);
    if (belowRetryTimer.current != null) window.clearTimeout(belowRetryTimer.current);
  }, []);

  // Load the next batch when the active item nears the bottom of the window.
  useEffect(() => {
    if (!items?.length || activeId == null || initPending.current) return;
    if (items.findIndex((item) => item.id === activeId) < items.length - 3) return;
    const plan = liveSource.current?.loadBelow?.(machine.current);
    if (!plan) return;
    const begun = beginLoadBelow(machine.current, plan.consumeIds, plan.retryOnFailure);
    if (!begun) return; // a below batch is already in flight
    machine.current = begun;
    const generation = begun.generation;
    plan.fetch()
      .then((batch) => {
        const prev = machine.current;
        const next = completeLoadBelow(prev, generation, batch.items, batch.cursor);
        if (next === prev) return; // stale — the source changed while the batch was in flight
        machine.current = next;
        setItems(next.items);
      })
      .catch(() => {
        // transient — the sentinel stays and the next scroll retries
        machine.current = failLoadBelow(machine.current, generation);
        if (!plan.retryOnFailure) return;
        // A channel can finish while its next selection page is loading, so no
        // later scroll may arrive to trigger the normal retry path.
        belowRetryTimer.current = window.setTimeout(() => {
          if (generation === machine.current.generation) {
            setBelowRetryTick((tick) => tick + 1);
          }
        }, 1_000);
      });
  }, [items, activeId, belowRetryTick]);

  // Pull in earlier results when scrolling up near the top of a bounded window.
  useEffect(() => {
    if (!items?.length || activeId == null || initPending.current) return;
    if (items.findIndex((item) => item.id === activeId) > 2) return;
    const plan = liveSource.current?.loadAbove?.(machine.current);
    if (!plan) return;
    const begun = beginLoadAbove(machine.current);
    if (!begun) return; // an above batch is already in flight
    machine.current = begun;
    const generation = begun.generation;
    plan.fetch()
      .then((batch) => {
        const prev = machine.current;
        const next = completeLoadAbove(prev, generation, batch, plan.idStart);
        if (next === prev) return;
        machine.current = next;
        pendingPrepend.current = batch.length; // keep the view fixed after prepending
        setItems(next.items);
      })
      .catch(() => {
        machine.current = failLoadAbove(machine.current, generation);
      });
  }, [items, activeId]);

  // Bound the window behind the active item so long sessions stay light.
  useEffect(() => {
    const root = containerRef.current;
    // Filtered and queue feeds are bounded, so they keep their loaded windows
    // instead of trimming (a queue has no loader to bring dropped items back).
    if (kind === "filtered" || kind === "queue" || activeId == null || !root) return;
    const activeIndex = items?.findIndex((item) => item.id === activeId) ?? -1;
    const prev = machine.current;
    const { state: next, plan } = trimWindow(prev, activeIndex, root.scrollTop, root.clientHeight, KEEP_BEHIND);
    if (next === prev) return;
    machine.current = next;
    pendingTrim.current = plan;
    setItems(next.items);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, items, kind]);

  useLayoutEffect(() => {
    const root = containerRef.current;
    if (!root) return;
    if (pendingScrollToId.current != null) {
      const index = items?.findIndex((item) => item.id === pendingScrollToId.current) ?? -1;
      if (index >= 0) root.scrollTop = index * root.clientHeight; // open at the clicked result
      pendingScrollToId.current = null;
      return;
    }
    if (pendingPrepend.current > 0) {
      root.scrollTop += prependScrollAdjustment(pendingPrepend.current, root.clientHeight); // hold position after prepend
      pendingPrepend.current = 0;
      return;
    }
    const plan = pendingTrim.current;
    if (!plan) return;
    root.scrollTop = plan.restoredScrollTop;
    pendingTrim.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items]);

  const updateItem = useCallback((updated: Item) => {
    machine.current = {
      ...machine.current,
      items: machine.current.items.map((item) => (item.id === updated.id ? updated : item)),
    };
    setItems((current) => current?.map((item) => (item.id === updated.id ? updated : item)) ?? null);
  }, []);

  const activePosition = activeId != null ? positions.current?.get(activeId) ?? null : null;

  return { items, error, activeId, setActiveId, transitionTargetId, kind, switchingTo, total, label, activePosition, updateItem };
}

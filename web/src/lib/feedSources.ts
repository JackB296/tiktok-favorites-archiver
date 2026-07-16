import { api } from "./api";
import { isFeedItem } from "./feedItems";
import type { Item } from "./types";
import { aboveIdSlice, belowIdSlice } from "./feedWindow";
import type { AbovePlan, BelowPlan, FeedInit, FeedSource, FeedWindowState } from "./feedWindow";

const BATCH_SIZE = 50;
/** How many earlier results to preload so scroll-up works (window ≤ itemSelection's 100 cap). */
const FILTERED_BEFORE = 45;

/** The api calls the sources make — injectable so the Node harness can fake them. */
export type FeedClient = Pick<typeof api, "feedIds" | "itemIds" | "itemPage" | "itemSelection" | "itemWindow">;

/** Below batch for sources with a fully known id order: request the next id slice. */
function selectionBelow(client: FeedClient, state: FeedWindowState<Item>): BelowPlan<Item> | null {
  const ids = belowIdSlice(state, BATCH_SIZE);
  if (!ids.length) return null;
  return {
    consumeIds: ids.length,
    fetch: () => client.itemSelection(ids).then((selected) => ({ items: selected.filter(isFeedItem) })),
  };
}

/** Below batch for cursor streams: request the next latest-order page. */
function cursorBelow(client: FeedClient, state: FeedWindowState<Item>): BelowPlan<Item> | null {
  const cursor = state.cursor;
  if (cursor == null) return null;
  return {
    consumeIds: 0,
    fetch: () => client.itemPage({ limit: BATCH_SIZE, cursor, order: "latest", feed: true })
      .then((page) => ({ items: page.items.filter(isFeedItem), cursor: page.next_cursor })),
  };
}

async function latestInit(client: FeedClient): Promise<FeedInit<Item>> {
  const page = await client.itemPage({ limit: BATCH_SIZE, order: "latest", feed: true });
  const items = page.items.filter(isFeedItem);
  return { items, cursor: page.next_cursor, activeId: items[0]?.id ?? null };
}

/** The default archive feed: newest favorites first, paged by cursor. */
export function latestFeedSource(key: string, opts: { scrollToTop?: boolean; keepOnError?: boolean } = {}, client: FeedClient = api): FeedSource<Item> {
  return {
    key,
    kind: "latest",
    loadInitial: async () => {
      try {
        const init = await latestInit(client);
        return opts.scrollToTop ? { ...init, scrollTo: "top" } : init;
      } catch (error) {
        if (opts.keepOnError) return null; // keep the current feed usable
        throw error;
      }
    },
    loadBelow: (state) => cursorBelow(client, state),
  };
}

/** Reopen the archive at the last watched favorite, then continue in latest order. */
export function resumeFeedSource(itemId: number, key: string, client: FeedClient = api): FeedSource<Item> {
  return {
    key,
    kind: "latest",
    loadInitial: async () => {
      const page = await client.itemWindow(itemId).catch(() => null);
      if (!page?.items.length) return null; // nothing to resume — keep the current feed
      return {
        items: page.items.filter(isFeedItem),
        cursor: page.items[page.items.length - 1]?.id ?? null,
        activeId: itemId,
        scrollTo: "top",
      };
    },
    loadBelow: (state) => cursorBelow(client, state),
  };
}

/** A curated Gallery selection: plays exactly the picked ids. */
export function queueFeedSource(ids: number[], key: string, client: FeedClient = api): FeedSource<Item> {
  return {
    key,
    kind: "queue",
    loadInitial: async () => {
      const selected = await client.itemSelection(ids);
      const items = selected.filter(isFeedItem);
      return { items, ids, idStart: 0, idEnd: ids.length, activeId: items[0]?.id ?? null, total: items.length };
    },
    // a curated queue ends at its final selected item — no loadBelow/loadAbove
  };
}

/**
 * Opening a Favorite scopes a windowed feed over feed_ids — the whole archive
 * in latest order, or the active search/filter — opened at the clicked item so
 * you can scroll both up (newer) and down (older) from it. Falls back to the
 * plain latest feed when the ids cannot load or the clicked item is not in them.
 */
export function filteredFeedSource(filterKey: string, requestedItemId: number, key: string, client: FeedClient = api): FeedSource<Item> {
  return {
    key,
    kind: "filtered",
    loadInitial: async () => {
      let listTotal: number | null = null;
      try {
        const ids = await client.feedIds(filterKey);
        listTotal = ids.length;
        const clickedIndex = ids.indexOf(requestedItemId);
        if (clickedIndex >= 0) {
          const start = Math.max(0, clickedIndex - FILTERED_BEFORE);
          const end = Math.min(ids.length, clickedIndex + BATCH_SIZE);
          const selected = await client.itemSelection(ids.slice(start, end));
          return {
            items: selected.filter(isFeedItem),
            ids,
            idStart: start,
            idEnd: end,
            activeId: requestedItemId,
            total: ids.length,
            scrollTo: "target",
          };
        }
      } catch {
        // fall through to the plain latest feed
      }
      const init = await latestInit(client);
      return listTotal == null ? init : { ...init, total: listTotal };
    },
    loadBelow: (state) => (state.ids.length ? selectionBelow(client, state) : cursorBelow(client, state)),
    loadAbove: (state): AbovePlan<Item> | null => {
      const slice = aboveIdSlice(state, BATCH_SIZE);
      if (!slice) return null;
      return {
        idStart: slice.start,
        fetch: () => client.itemSelection(slice.ids).then((selected) => selected.filter(isFeedItem)),
      };
    },
  };
}

/** A fresh shuffle over every favorite id, paged through in shuffled order. */
export function randomFeedSource(key: string, client: FeedClient = api): FeedSource<Item> {
  return {
    key,
    kind: "random",
    loadInitial: async () => {
      try {
        const ids = await client.itemIds();
        if (!ids.length) return null;
        for (let i = ids.length - 1; i > 0; i -= 1) {
          const j = Math.floor(Math.random() * (i + 1));
          [ids[i], ids[j]] = [ids[j], ids[i]];
        }
        const first = ids.slice(0, BATCH_SIZE);
        const selected = await client.itemSelection(first);
        const items = selected.filter(isFeedItem);
        return { items, ids, idStart: 0, idEnd: first.length, activeId: items[0]?.id ?? null, total: ids.length, scrollTo: "top" };
      } catch {
        return null; // keep the current feed usable if randomization cannot be loaded
      }
    },
    loadBelow: (state) => selectionBelow(client, state),
  };
}

/** List helpers shared by every saved-list machine (Gallery presets, term
    lists, playback queues, song playlists). Pure so Node tests can hit them. */

/** A new entry slotted into name order (locale compare, ties keep the existing
    entry first) — the sort every saved-list copy used after a create. */
export function sortedInsert<T extends { name: string }>(list: T[], item: T): T[] {
  return [...list, item].sort((a, b) => a.name.localeCompare(b.name));
}

export function removeById<T extends { id: number }>(list: T[], id: number): T[] {
  return list.filter((entry) => entry.id !== id);
}

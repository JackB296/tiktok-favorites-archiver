type ChannelItem = { id: number };

export type ChannelAdvanceAction =
  | { kind: "advance"; itemId: number }
  | { kind: "restart" }
  | { kind: "wait" };

/** The next loaded item for a channel, or null until pagination makes it available. */
export function channelAdvanceTarget(items: readonly ChannelItem[], activeId: number | null): number | null {
  if (activeId == null) return null;
  const activeIndex = items.findIndex((item) => item.id === activeId);
  return activeIndex < 0 ? null : items[activeIndex + 1]?.id ?? null;
}

/**
 * Advance through loaded cards, wait for an in-flight page, or resolve the
 * live collection again once its final card finishes.
 */
export function channelAdvanceAction(
  items: readonly ChannelItem[],
  activeId: number | null,
  activePosition: number | null,
  total: number | null,
): ChannelAdvanceAction {
  const activeIndex = activeId == null ? -1 : items.findIndex((item) => item.id === activeId);
  if (activeIndex < 0) return { kind: "wait" };
  const nextId = channelAdvanceTarget(items, activeId);
  if (nextId != null) return { kind: "advance", itemId: nextId };
  if (activePosition != null && total != null && activePosition === total - 1) {
    return { kind: "restart" };
  }
  return { kind: "wait" };
}

/** Distinct keys force an ended channel item to mount a fresh media element. */
export function channelMediaKey(itemId: number, channelMode: boolean, playbackGeneration: number): string {
  return channelMode ? `${itemId}:${playbackGeneration}` : String(itemId);
}

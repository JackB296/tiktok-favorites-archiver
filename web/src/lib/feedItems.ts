import type { Item } from "./types";

/** Feed entries include playable media plus durable markers for dead originals. */
export function isFeedItem(item: Pick<Item, "status" | "video_url" | "images">) {
  return Boolean(item.video_url || item.images.length || item.status === "expired");
}

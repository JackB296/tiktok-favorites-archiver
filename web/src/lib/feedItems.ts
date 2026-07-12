import type { Item } from "./types";

type FeedMedia = Pick<Item, "status" | "video_url" | "images" | "offloaded">;
export type FeedMediaKind = "video" | "slideshow" | "offloaded" | "expired" | "empty";

/** Prefer media that is actually present; otherwise retain durable archive markers. */
export function feedMediaKind(item: FeedMedia): FeedMediaKind {
  if (item.video_url) return "video";
  if (item.images.length) return "slideshow";
  if (item.offloaded) return "offloaded";
  if (item.status === "expired") return "expired";
  return "empty";
}

/** Feed entries include playable media plus durable markers for dead originals. */
export function isFeedItem(item: FeedMedia) {
  return feedMediaKind(item) !== "empty";
}

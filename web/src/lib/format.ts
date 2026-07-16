/** Shared value formatters and labels. Each formatter keeps the exact output of
    the call sites it was extracted from, so routes render identically. */

/** Human label for a favorite's audio probe result. */
export function audioStatus(hasAudio: boolean | null, audioSilent?: boolean | null): "No audio" | "Has audio" | "Not checked" | "Silent" {
  if (audioSilent) return "Silent";
  if (hasAudio === false) return "No audio";
  if (hasAudio === true) return "Has audio";
  return "Not checked";
}

/** Playback clock: "1:05". Floors, and treats unknown or invalid input as 0:00. */
export function formatMediaTime(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

/** A favorite's duration: "1:05", or "45s" under a minute; null when unindexed. */
export function formatDuration(seconds: number): string;
export function formatDuration(seconds: number | null): string | null;
export function formatDuration(seconds: number | null): string | null {
  if (seconds == null) return null;
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  return minutes ? `${minutes}:${String(total % 60).padStart(2, "0")}` : `${total}s`;
}

/** Library-wide runtime: "1.5 hours" (whole hours from 10 up), "45 min" under an hour. */
export function formatRuntime(seconds: number): string {
  const hours = seconds / 3600;
  return hours >= 1 ? `${hours.toFixed(hours >= 10 ? 0 : 1)} hours` : `${Math.round(seconds / 60)} min`;
}

/** File size: "1.2 GB" / "34.5 MB"; null when the size is unknown. */
export function formatSize(bytes: number): string;
export function formatSize(bytes: number | null): string | null;
export function formatSize(bytes: number | null): string | null {
  if (bytes == null) return null;
  return bytes >= 1_000_000_000 ? `${(bytes / 1_000_000_000).toFixed(1)} GB` : `${(bytes / 1_000_000).toFixed(1)} MB`;
}

/** Only http(s) links are safe to render as anchors; anything else stays plain text. */
export function isSafeHttpUrl(link: string): boolean {
  return /^https?:\/\//i.test(link);
}

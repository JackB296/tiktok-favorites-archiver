export type ViewerShortcut = "pause" | "mute" | "previous" | "next" | "prevImage" | "nextImage" | "fullscreen" | "details";

export function viewerShortcut({ key, code, repeat, editing, onControl = false }: {
  key: string;
  code: string;
  repeat: boolean;
  /** Focus is in a text field, where every key belongs to the field. */
  editing: boolean;
  /** Focus is on a button, link or select. Only Space is off limits there —
   * it activates the control — so the rest of the feed keys keep working
   * after someone clicks the details toggle or a caption link. */
  onControl?: boolean;
}): ViewerShortcut | null {
  if (editing) return null;
  if (key === " " || code === "Space") return repeat || onControl ? null : "pause";
  if (key.toLowerCase() === "m") return repeat ? null : "mute";
  if (key.toLowerCase() === "f") return repeat ? null : "fullscreen";
  if (key.toLowerCase() === "c") return repeat ? null : "details";
  if (key === "ArrowDown") return "next";
  if (key === "ArrowUp") return "previous";
  if (key === "ArrowRight") return "nextImage";
  if (key === "ArrowLeft") return "prevImage";
  return null;
}

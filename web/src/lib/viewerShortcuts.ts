export type ViewerShortcut = "pause" | "mute" | "previous" | "next" | "prevImage" | "nextImage" | "fullscreen";

export function viewerShortcut({ key, code, repeat, editing }: {
  key: string;
  code: string;
  repeat: boolean;
  editing: boolean;
}): ViewerShortcut | null {
  if (editing) return null;
  if (key === " " || code === "Space") return repeat ? null : "pause";
  if (key.toLowerCase() === "m") return repeat ? null : "mute";
  if (key.toLowerCase() === "f") return repeat ? null : "fullscreen";
  if (key === "ArrowDown") return "next";
  if (key === "ArrowUp") return "previous";
  if (key === "ArrowRight") return "nextImage";
  if (key === "ArrowLeft") return "prevImage";
  return null;
}

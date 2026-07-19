import type { CaptionSegment } from "./types";

export type LensSnippetPart = { text: string; highlight: boolean };

export function lensSnippetParts(value: unknown): LensSnippetPart[];
export function lensSourceLabel(source: string): string;
export function readLensStartTime(value: string | null): number | null;
export function mediaStartRequest(
  src: string,
  startAtS: number | null,
  duration: number,
): { signature: string; time: number } | null;
export function readCaptionPreference(value: string | null): boolean;
export function activeTranscriptCaption(
  segments: CaptionSegment[],
  currentTime: number,
): CaptionSegment | null;

import { useEffect, useRef, useState } from "react";
import { Check, Info, Play, SpeakerSlash } from "@phosphor-icons/react";
import type { Item } from "../lib/types";
import type { GalleryDetails } from "../lib/galleryPresentation.js";
import {
  GALLERY_HOVER_PREVIEW_DELAY_MS,
  galleryHoverPreviewUrl,
  shouldStopGalleryPreview,
} from "../lib/galleryPresentation.js";
import { audioStatus, formatDuration, formatSize } from "../lib/format";
import { cx } from "./ui";

export function GalleryThumbnail({
  item, details, cardWidth, onClick, onPreviewStart, onPreviewEnd,
  selecting = false, inspecting = false, selected = false,
  previewEnabled = false, previewActive = false,
}: {
  item: Item;
  details: GalleryDetails;
  cardWidth: number;
  onClick: () => void;
  onPreviewStart: (itemId: number) => void;
  onPreviewEnd: (itemId: number) => void;
  selecting?: boolean;
  inspecting?: boolean;
  selected?: boolean;
  previewEnabled?: boolean;
  previewActive?: boolean;
}) {
  const previewTimerRef = useRef<number | null>(null);
  const duration = formatDuration(item.duration_s);
  const resolution = item.media_width && item.media_height ? `${item.media_width}×${item.media_height}` : null;
  const size = formatSize(item.media_size);
  // Card sets its own font size from its measured width, so every em-based badge,
  // caption, and icon below scales with the chosen thumbnail size (floored so text
  // stays legible on the smallest step, capped so it never dominates the largest).
  const fontSize = `${Math.min(26, Math.max(9, Math.round(cardWidth * 0.062)))}px`;
  const canPreview = previewEnabled && item.kind === "video" && Boolean(item.video_url);

  const clearPreviewTimer = () => {
    if (previewTimerRef.current === null) return;
    window.clearTimeout(previewTimerRef.current);
    previewTimerRef.current = null;
  };

  useEffect(() => () => {
    clearPreviewTimer();
    onPreviewEnd(item.id);
  }, [item.id, onPreviewEnd]);

  useEffect(() => {
    if (canPreview) return;
    clearPreviewTimer();
    if (previewActive) onPreviewEnd(item.id);
  }, [canPreview, item.id, onPreviewEnd, previewActive]);

  return (
    <button
      onClick={onClick}
      onPointerEnter={(event) => {
        if (!canPreview || event.pointerType !== "mouse") return;
        clearPreviewTimer();
        previewTimerRef.current = window.setTimeout(() => {
          previewTimerRef.current = null;
          onPreviewStart(item.id);
        }, GALLERY_HOVER_PREVIEW_DELAY_MS);
      }}
      onPointerLeave={() => {
        clearPreviewTimer();
        onPreviewEnd(item.id);
      }}
      style={{ fontSize }}
      aria-label={`${selecting ? selected ? "Unselect" : "Select" : inspecting ? "Inspect" : "Play"} favorite #${item.id}${item.caption ? `: ${item.caption}` : ""}`}
      aria-pressed={selecting ? selected : undefined}
      className={cx("group relative aspect-[9/16] overflow-hidden rounded-[var(--radius-media)] bg-black text-left", selected && "ring-2 ring-accent ring-offset-2 ring-offset-canvas")}
    >
      {item.thumbnail_url ? (
        <img
          src={item.thumbnail_url}
          alt=""
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : item.images[0] ? (
        <img
          src={item.images[0]}
          alt=""
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : (
        <div className="tabular flex h-full w-full items-center justify-center text-[1.1em] text-ink-faint">#{item.id}</div>
      )}
      {previewActive && canPreview && item.video_url && <GalleryHoverPreview src={item.video_url} />}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
      {details.archiveNumber && <span className="tabular absolute left-[0.55em] top-[0.55em] rounded bg-black/50 px-[0.4em] py-[0.15em] text-[0.78em] text-white/80">
        #{item.id}
      </span>}
      {(item.has_audio === false || item.audio_silent === true) && <span title="No sound — no audio stream, or a stream that is silent. You can replace the file from its Feed settings." className="absolute left-[0.55em] top-[2.5em] inline-flex items-center gap-[0.3em] rounded bg-bad/90 px-[0.4em] py-[0.15em] text-[0.78em] font-semibold text-white"><SpeakerSlash size="1em" weight="fill" />{audioStatus(item.has_audio, item.audio_silent)}</span>}
      {selecting && <span aria-hidden="true" className={cx("absolute right-[0.55em] top-[0.55em] flex h-[1.5em] w-[1.5em] items-center justify-center rounded-full border", selected ? "border-accent bg-accent text-on-accent" : "border-white/70 bg-black/50 text-white/80")}>{selected ? <Check size="1em" weight="bold" /> : null}</span>}
      {inspecting && <span aria-hidden="true" className="absolute right-[0.55em] top-[0.55em] flex h-[1.5em] w-[1.5em] items-center justify-center rounded-full border border-white/70 bg-black/50 text-white/80"><Info size="1em" /></span>}
      <div className={cx("absolute top-[0.55em] flex max-w-[65%] flex-col items-end gap-[0.3em] text-[0.78em] text-white/85", selecting || inspecting ? "right-[2.5em]" : "right-[0.55em]")}>
        {((details.duration && duration) || (details.resolution && resolution)) && <span className="rounded bg-black/50 px-[0.4em] py-[0.15em]">{[details.duration ? duration : null, details.resolution ? resolution : null].filter(Boolean).join(" · ")}</span>}
        {!selecting && !inspecting && <span className="rounded-full bg-black/40 p-[0.35em] opacity-0 transition group-hover:opacity-100"><Play size="1em" weight="fill" /></span>}
      </div>
      <div className="absolute inset-x-0 bottom-0 p-[0.7em]">
        {item.status === "failed" && <p title={item.error ?? undefined} className="truncate text-[0.78em] font-medium text-bad">{item.error ?? "Download failed"}</p>}
        {item.status === "expired" && <p title="TikTok no longer serves the original link. Its archive number is preserved and Sync will not retry it automatically." className="truncate text-[0.78em] font-medium text-white/60">Original unavailable</p>}
        {item.status === "ignored" && <p title="Marked as don't-download. Its archive number is preserved and Sync will not attempt it." className="truncate text-[0.78em] font-medium text-white/60">Not downloading</p>}
        {item.offloaded && <span title="Archived on external storage, so it is not flagged as missing here." className="mb-[0.3em] inline-block rounded bg-black/50 px-[0.4em] py-[0.15em] text-[0.78em] font-medium text-white/80">offloaded</span>}
        {details.author && item.author && <p className="truncate text-[0.85em] font-medium text-white">{item.author}</p>}
        {details.caption && item.caption && <p className="truncate text-[0.78em] text-white/70">{item.caption}</p>}
        {details.technical && (item.media_codec || size) && <p className="mt-[0.15em] truncate text-[0.78em] text-white/70 opacity-0 transition group-hover:opacity-100">{[item.media_codec, size].filter(Boolean).join(" · ")}</p>}
      </div>
    </button>
  );
}

function GalleryHoverPreview({ src }: { src: string }) {
  const [playing, setPlaying] = useState(false);
  const [finished, setFinished] = useState(false);
  if (finished) return null;
  return (
    <video
      src={galleryHoverPreviewUrl(src)}
      autoPlay
      muted
      playsInline
      preload="metadata"
      disablePictureInPicture
      controlsList="nodownload noremoteplayback"
      aria-hidden="true"
      onPlaying={() => setPlaying(true)}
      onTimeUpdate={(event) => {
        if (shouldStopGalleryPreview(event.currentTarget.currentTime)) setFinished(true);
      }}
      onEnded={() => setFinished(true)}
      onError={() => setFinished(true)}
      className={cx("pointer-events-none absolute inset-0 z-[1] h-full w-full object-cover transition-opacity duration-150", playing ? "opacity-100" : "opacity-0")}
    />
  );
}

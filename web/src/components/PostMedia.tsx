import { useEffect, useRef, useState } from "react";
import { CaretLeft, CaretRight } from "@phosphor-icons/react";
import type { Item } from "../lib/types";
import { cx } from "./ui";
import { usePlayback } from "./playback";

/**
 * Renders a post's media, letterboxed on black (matching the Plex/slideshow look):
 * videos autoplay while `active`; slideshows auto-advance (2.5s) with their audio,
 * plus manual prev/next. Nothing plays unless `active`.
 */
export function PostMedia({ item, active, preload = false }: { item: Item; active: boolean; preload?: boolean }) {
  const { muted } = usePlayback();
  if (!active && !preload) return <MediaPlaceholder />;
  if (item.video_url) return <VideoMedia src={item.video_url} active={active} muted={muted} preload={preload} />;
  if (item.images.length) return <SlideMedia images={item.images} audio={item.audio} active={active} muted={muted} />;
  return <div className="flex h-full w-full items-center justify-center text-sm text-ink-faint">no media yet</div>;
}

function MediaPlaceholder() {
  return <div aria-hidden="true" className="h-full w-full bg-black" />;
}

function VideoMedia({ src, active, muted, preload }: { src: string; active: boolean; muted: boolean; preload: boolean }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (active) v.play().catch(() => {});
    else v.pause();
  }, [active]);
  useEffect(() => {
    if (ref.current) ref.current.muted = muted;
  }, [muted]);
  return <video ref={ref} src={src} preload={active || preload ? "auto" : "none"} loop playsInline muted className="max-h-full max-w-full object-contain" />;
}

const SLIDE_MS = 2500;

function SlideMedia({
  images,
  audio,
  active,
  muted,
}: {
  images: string[];
  audio: string | null;
  active: boolean;
  muted: boolean;
}) {
  const [idx, setIdx] = useState(0);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    if (!active || images.length < 2) return;
    const t = window.setInterval(() => setIdx((i) => (i + 1) % images.length), SLIDE_MS);
    return () => window.clearInterval(t);
  }, [active, images.length]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    a.muted = muted;
    if (active) a.play().catch(() => {});
    else {
      a.pause();
      a.currentTime = 0;
    }
  }, [active, muted]);

  const go = (delta: number) => setIdx((i) => (i + delta + images.length) % images.length);

  return (
    <div className="relative flex h-full w-full items-center justify-center">
      <img src={images[idx]} alt="" className="max-h-full max-w-full object-contain" />
      {audio && <audio ref={audioRef} src={audio} loop />}
      {images.length > 1 && (
        <>
          <SlideNav side="left" onClick={() => go(-1)} />
          <SlideNav side="right" onClick={() => go(1)} />
          <div className="absolute bottom-4 left-1/2 flex -translate-x-1/2 gap-1.5">
            {images.map((_, i) => (
              <span
                key={i}
                className={cx(
                  "h-1.5 rounded-full transition-all duration-200",
                  i === idx ? "w-4 bg-white" : "w-1.5 bg-white/40",
                )}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function SlideNav({ side, onClick }: { side: "left" | "right"; onClick: () => void }) {
  const Icon = side === "left" ? CaretLeft : CaretRight;
  return (
    <button
      onClick={onClick}
      aria-label={side === "left" ? "Previous image" : "Next image"}
      className={cx(
        "absolute top-1/2 -translate-y-1/2 rounded-full bg-black/40 p-2 text-white backdrop-blur-sm",
        "transition hover:bg-black/60 active:translate-y-[calc(-50%+1px)]",
        side === "left" ? "left-3" : "right-3",
      )}
    >
      <Icon size={20} weight="bold" />
    </button>
  );
}

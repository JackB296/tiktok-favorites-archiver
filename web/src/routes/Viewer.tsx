import { useEffect, useRef, useState } from "react";
import { SpeakerSimpleHigh, SpeakerSimpleX, ArrowSquareOut, FilmReel } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { PostMedia } from "../components/PostMedia";
import { EmptyState, Skeleton } from "../components/ui";

export function Viewer() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [muted, setMuted] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .items()
      .then((list) => {
        const playable = list.filter((i) => i.video_url || i.images.length);
        setItems(playable);
        if (playable[0]) setActiveId(playable[0].id);
      })
      .catch(() => setItems([]));
  }, []);

  useEffect(() => {
    const root = containerRef.current;
    if (!root || !items?.length) return;
    const io = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (top) {
          const id = Number((top.target as HTMLElement).dataset.id);
          if (!Number.isNaN(id)) setActiveId(id);
        }
      },
      { root, threshold: 0.6 },
    );
    root.querySelectorAll("[data-id]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [items]);

  if (!items) {
    return (
      <div className="mx-auto max-w-md p-4">
        <Skeleton className="h-[82dvh] w-full !rounded-[var(--radius-media)]" />
      </div>
    );
  }
  if (!items.length) {
    return (
      <EmptyState
        icon={<FilmReel size={40} />}
        title="Nothing to watch yet"
        hint="Import your TikTok export and run a sync from the Sync tab, and your favorites show up here."
      />
    );
  }

  const Speaker = muted ? SpeakerSimpleX : SpeakerSimpleHigh;

  return (
    <div ref={containerRef} className="h-full snap-y snap-mandatory overflow-y-scroll bg-black">
      {items.map((item) => (
        <section
          key={item.id}
          data-id={item.id}
          className="relative flex h-full snap-start items-center justify-center"
        >
          <PostMedia item={item} active={item.id === activeId} muted={muted} />

          <button
            onClick={() => setMuted((m) => !m)}
            aria-label={muted ? "Unmute" : "Mute"}
            className="absolute right-4 top-4 rounded-full bg-black/40 p-2.5 text-white backdrop-blur-sm transition hover:bg-black/60 active:translate-y-px"
          >
            <Speaker size={20} weight="fill" />
          </button>

          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-5 pt-20">
            <div className="mx-auto max-w-md">
              {item.author && <p className="text-sm font-semibold text-white">{item.author}</p>}
              {item.caption && <p className="mt-1 line-clamp-2 text-sm text-white/80">{item.caption}</p>}
              <a
                href={item.link}
                target="_blank"
                rel="noreferrer"
                className="pointer-events-auto mt-2 inline-flex items-center gap-1.5 text-xs text-white/60 hover:text-white"
              >
                <span className="tabular">#{item.id}</span>
                <ArrowSquareOut size={13} />
                open on TikTok
              </a>
            </div>
          </div>
        </section>
      ))}
    </div>
  );
}

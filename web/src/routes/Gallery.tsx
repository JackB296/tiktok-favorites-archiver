import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  MagnifyingGlass,
  X,
  Play,
  SpeakerSimpleHigh,
  SpeakerSimpleX,
  ImageSquare,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { PostMedia } from "../components/PostMedia";
import { EmptyState, Skeleton, cx } from "../components/ui";

const FILTERS = [
  { key: "", label: "All" },
  { key: "video", label: "Videos" },
  { key: "slideshow", label: "Slideshows" },
];

export function Gallery() {
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [items, setItems] = useState<Item[] | null>(null);
  const [selected, setSelected] = useState<Item | null>(null);

  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(() => {
      api
        .items({ search, kind })
        .then((list) => alive && setItems(list))
        .catch(() => alive && setItems([]));
    }, 200); // debounce typing
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [search, kind]);

  return (
    <div className="h-full overflow-y-auto">
    <div className="mx-auto max-w-[1400px] px-4 py-6">
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <MagnifyingGlass size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search caption, hashtag, author"
            className="h-10 w-full rounded-[var(--radius-control)] border border-line bg-surface pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
          />
        </div>
        <div className="flex gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              onClick={() => setKind(f.key)}
              className={cx(
                "rounded-full px-3 py-1.5 text-xs font-medium transition",
                kind === f.key ? "bg-accent text-on-accent" : "border border-line text-ink-dim hover:text-ink",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {!items ? (
        <Grid>
          {Array.from({ length: 10 }).map((_, i) => (
            <Skeleton key={i} className="aspect-[9/16] !rounded-[var(--radius-media)]" />
          ))}
        </Grid>
      ) : !items.length ? (
        <EmptyState
          icon={<ImageSquare size={40} />}
          title="No matches"
          hint="Try a different search, or import your export and run a sync."
        />
      ) : (
        <Grid>
          {items.map((it) => (
            <Thumb key={it.id} item={it} onClick={() => setSelected(it)} />
          ))}
        </Grid>
      )}

      {selected && <Lightbox item={selected} onClose={() => setSelected(null)} />}
    </div>
    </div>
  );
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">{children}</div>;
}

function Thumb({ item, onClick }: { item: Item; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group relative aspect-[9/16] overflow-hidden rounded-[var(--radius-media)] bg-black text-left"
    >
      {item.images[0] ? (
        <img
          src={item.images[0]}
          alt=""
          loading="lazy"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : item.video_url ? (
        <video
          src={item.video_url}
          muted
          playsInline
          preload="metadata"
          className="h-full w-full object-cover opacity-90 transition group-hover:opacity-100"
        />
      ) : (
        <div className="tabular flex h-full w-full items-center justify-center text-ink-faint">#{item.id}</div>
      )}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
      <span className="tabular absolute left-2 top-2 rounded bg-black/50 px-1.5 py-0.5 text-[10px] text-white/80">
        #{item.id}
      </span>
      <span className="absolute right-2 top-2 rounded-full bg-black/40 p-1 text-white opacity-0 transition group-hover:opacity-100">
        <Play size={12} weight="fill" />
      </span>
      <div className="absolute inset-x-0 bottom-0 p-2.5">
        {item.author && <p className="truncate text-xs font-medium text-white">{item.author}</p>}
        {item.caption && <p className="truncate text-[11px] text-white/70">{item.caption}</p>}
      </div>
    </button>
  );
}

function Lightbox({ item, onClose }: { item: Item; onClose: () => void }) {
  const [muted, setMuted] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const Speaker = muted ? SpeakerSimpleX : SpeakerSimpleHigh;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 p-4" onClick={onClose}>
      <button
        onClick={onClose}
        aria-label="Close"
        className="absolute right-4 top-4 rounded-full bg-white/10 p-2 text-white transition hover:bg-white/20"
      >
        <X size={20} />
      </button>
      <div
        className="relative flex h-full max-h-[90dvh] w-full max-w-md items-center justify-center"
        onClick={(e) => e.stopPropagation()}
      >
        <PostMedia item={item} active muted={muted} />
        <button
          onClick={() => setMuted((m) => !m)}
          aria-label={muted ? "Unmute" : "Mute"}
          className="absolute right-3 top-3 rounded-full bg-black/40 p-2 text-white backdrop-blur-sm transition hover:bg-black/60"
        >
          <Speaker size={18} weight="fill" />
        </button>
        {(item.author || item.caption) && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-4">
            {item.author && <p className="text-sm font-semibold text-white">{item.author}</p>}
            {item.caption && <p className="mt-1 line-clamp-2 text-sm text-white/80">{item.caption}</p>}
          </div>
        )}
      </div>
    </div>
  );
}

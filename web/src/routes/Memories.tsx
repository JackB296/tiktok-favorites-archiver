import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CalendarBlank, Play, Sparkle } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { MemoryResponse, MemorySection } from "../lib/types";
import { EmptyState, Skeleton } from "../components/ui";
import { memoryDateLabel, memoryFeedUrl } from "../lib/memoryPresentation.js";

function MemoryShelf({ section }: { section: MemorySection }) {
  if (!section.items.length) return null;
  return (
    <section className="border-t border-line py-6 first:border-t-0 first:pt-0">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-ink">{section.title}</h2>
          <p className="mt-1 text-sm text-ink-dim">{section.description}</p>
        </div>
        <Link
          to={memoryFeedUrl(section.item_ids, section.item_ids[0])}
          className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
        >
          <Play size={14} weight="fill" /> Play all
        </Link>
      </div>
      <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {section.items.map((item) => (
          <li key={item.id}>
            <Link to={memoryFeedUrl(section.item_ids, item.id)} className="group block">
              <div className="relative aspect-[3/4] overflow-hidden rounded-[var(--radius-media)] bg-elevated">
                {item.thumbnail_url ? (
                  <img src={item.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover transition duration-300 group-hover:scale-[1.03]" />
                ) : (
                  <span aria-hidden className="flex h-full items-center justify-center text-ink-faint"><Sparkle size={28} /></span>
                )}
                <span className="absolute inset-0 flex items-center justify-center bg-black/0 opacity-0 transition group-hover:bg-black/30 group-hover:opacity-100">
                  <span className="rounded-full bg-white/90 p-2 text-black"><Play size={18} weight="fill" /></span>
                </span>
              </div>
              <p className="mt-2 line-clamp-2 text-sm font-medium leading-snug text-ink">
                {item.caption?.trim() || (item.author ? `@${item.author}` : `Favorite #${item.id}`)}
              </p>
              <p className="mt-0.5 text-xs text-ink-faint">{item.favorited_at?.slice(0, 10) || "Date unknown"}</p>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function Memories() {
  const [data, setData] = useState<MemoryResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api.memories().then(setData).catch((error) => setMessage((error as Error).message));
  }, []);

  if (!data && !message) {
    return <div className="mx-auto max-w-6xl space-y-3 px-4 py-8"><Skeleton className="h-24" /><Skeleton className="h-72" /></div>;
  }

  const populated = data?.sections.some((section) => section.items.length);
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Your archive, resurfaced</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">Memory Lane</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-dim">A private daily mix built from favorite dates and what you watch here. Play history stays in your local database.</p>
          </div>
          {data && <span className="inline-flex items-center gap-2 text-sm text-ink-dim"><CalendarBlank size={17} />{memoryDateLabel(data.date)}</span>}
        </div>

        {message ? (
          <EmptyState icon={<Sparkle size={40} />} title="Memory Lane could not load" hint={message} />
        ) : populated ? (
          <div>{data?.sections.map((section) => <MemoryShelf key={section.key} section={section} />)}</div>
        ) : (
          <EmptyState
            icon={<Sparkle size={40} />}
            title="No memories are ready yet"
            hint={<>Once locally playable favorites have dates, this page will make daily collections. Check the <Link to="/sync" className="text-accent hover:underline">Sync</Link> tab if your archive is still downloading.</>}
          />
        )}
      </div>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Check, Star, Tag } from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item } from "../lib/types";
import { Button, EmptyState, Skeleton, cx } from "../components/ui";

type Source = "unreviewed" | "forgotten";

export function Curate() {
  const [source, setSource] = useState<Source>("unreviewed");
  const [limit, setLimit] = useState(20);
  const [items, setItems] = useState<Item[] | null>(null);
  const [index, setIndex] = useState(0);
  const [starred, setStarred] = useState(false);
  const [tags, setTags] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const current = items?.[index] ?? null;

  const load = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      const session = await api.curateSession(source, limit);
      setItems(session.items);
      setIndex(0);
    } catch (error) {
      setItems([]);
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }, [limit, source]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!current) return;
    setStarred(current.annotation.starred);
    setTags(current.annotation.tags.join(", "));
    setNote(current.annotation.note);
    setMessage(null);
  }, [current?.id]);

  const advance = () => setIndex((value) => Math.min(items?.length ?? 0, value + 1));

  async function saveAndNext() {
    if (!current) return;
    setBusy(true);
    setMessage(null);
    try {
      const annotation = await api.updateItemAnnotation(current.id, {
        starred,
        note,
        tags: Array.from(new Set(tags.split(",").map((tag) => tag.trim()).filter(Boolean))),
        reviewed: true,
      });
      setItems((value) => value?.map((item) => item.id === current.id ? { ...item, annotation } : item) ?? null);
      advance();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const finished = items !== null && index >= items.length;
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Private archive curation</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">Curator Deck</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-dim">Build personal context one favorite at a time. Stars, notes, and tags stay in this local archive.</p>
          </div>
          <div className="flex items-end gap-2">
            <label className="text-xs text-ink-dim">Session
              <select value={source} onChange={(event) => setSource(event.target.value as Source)} className="mt-1 block h-9 rounded-[var(--radius-control)] border border-line bg-surface px-2 text-sm text-ink">
                <option value="unreviewed">Unreviewed</option>
                <option value="forgotten">Forgotten</option>
              </select>
            </label>
            <label className="text-xs text-ink-dim">Size
              <select value={limit} onChange={(event) => setLimit(Number(event.target.value))} className="mt-1 block h-9 rounded-[var(--radius-control)] border border-line bg-surface px-2 text-sm text-ink">
                {[10, 20, 30, 50].map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
          </div>
        </div>

        {items === null ? (
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_22rem]"><Skeleton className="aspect-video" /><Skeleton className="h-96" /></div>
        ) : finished || !current ? (
          <EmptyState
            icon={<Check size={42} />}
            title={message ? "The session could not load" : items.length ? "Session complete" : "Nothing needs review"}
            hint={message ?? <Button size="sm" onClick={() => void load()}>Start another session</Button>}
          />
        ) : (
          <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_23rem]">
            <section className="overflow-hidden rounded-[var(--radius-media)] border border-line bg-black">
              <div className="flex min-h-[28rem] items-center justify-center">
                {current.kind === "slideshow" && current.images[0] ? (
                  <img src={current.images[0]} alt="" className="max-h-[70dvh] w-full object-contain" />
                ) : current.video_url ? (
                  <video key={current.id} src={current.video_url} controls muted playsInline className="max-h-[70dvh] w-full object-contain" />
                ) : current.thumbnail_url ? (
                  <img src={current.thumbnail_url} alt="" className="max-h-[70dvh] w-full object-contain" />
                ) : <span className="text-sm text-white/60">Favorite #{current.id}</span>}
              </div>
              <div className="border-t border-white/10 bg-black px-4 py-3 text-white">
                <p className="text-xs text-white/50">{index + 1} of {items.length} · Favorite #{current.id}</p>
                <p className="mt-1 line-clamp-3 text-sm">{current.caption || "No caption"}</p>
                {current.author && <p className="mt-1 text-xs text-white/60">@{current.author}</p>}
              </div>
            </section>

            <section className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
              <button
                type="button"
                onClick={() => setStarred((value) => !value)}
                aria-pressed={starred}
                className={cx("flex w-full items-center gap-3 rounded-[var(--radius-control)] border px-3 py-3 text-left transition", starred ? "border-accent bg-accent/10 text-accent" : "border-line text-ink-dim hover:text-ink")}
              >
                <Star size={22} weight={starred ? "fill" : "regular"} />
                <span><span className="block text-sm font-semibold">Star this favorite</span><span className="text-xs">Use the Starred filter in Gallery later.</span></span>
              </button>
              <label className="mt-5 block text-sm font-medium text-ink"><span className="inline-flex items-center gap-2"><Tag size={16} />Private tags</span>
                <input value={tags} onChange={(event) => setTags(event.target.value)} maxLength={1020} placeholder="recipe, cozy, try later" className="mt-2 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm font-normal text-ink placeholder:text-ink-faint" />
                <span className="mt-1 block text-xs font-normal text-ink-faint">Comma separated, up to 20.</span>
              </label>
              <label className="mt-5 block text-sm font-medium text-ink">Private note
                <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} rows={7} placeholder="Why did you save this?" className="mt-2 w-full resize-y rounded-[var(--radius-control)] border border-line bg-elevated p-3 text-sm font-normal text-ink placeholder:text-ink-faint" />
                <span className="mt-1 block text-right text-xs font-normal text-ink-faint">{note.length} / 2000</span>
              </label>
              {message && <p role="alert" className="mt-3 text-xs text-bad">{message}</p>}
              <div className="mt-5 flex gap-2">
                <Button variant="ghost" onClick={advance} disabled={busy}>Skip</Button>
                <Button className="flex-1" onClick={() => void saveAndNext()} disabled={busy}>{busy ? "Saving…" : <>Save &amp; next <ArrowRight size={16} /></>}</Button>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}


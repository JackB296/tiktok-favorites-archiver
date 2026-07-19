import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  ArrowDown,
  ArrowUp,
  DownloadSimple,
  FilmReel,
  FloppyDisk,
  Plus,
  Scissors,
  Trash,
} from "@phosphor-icons/react";
import { api } from "../lib/api";
import type { Item, PlaybackQueue, Story, StoryChapter, StoryInput } from "../lib/types";
import { Button, EmptyState, Skeleton } from "../components/ui";
import { formatDuration } from "../lib/format";
import {
  moveStoryChapter,
  readStoryQueue,
  storyDuration,
} from "../lib/storyPresentation.js";

const EMPTY_STORY: StoryInput = { name: "", description: "", chapters: [] };

function chapterTitle(item: Item) {
  return (item.caption?.trim() || (item.author ? `@${item.author}` : `Favorite #${item.id}`)).slice(0, 120);
}

export function Stories() {
  const [searchParams] = useSearchParams();
  const [stories, setStories] = useState<Story[]>([]);
  const [queues, setQueues] = useState<PlaybackQueue[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedQueueId, setSelectedQueueId] = useState("");
  const [draft, setDraft] = useState<StoryInput>(EMPTY_STORY);
  const [items, setItems] = useState<Item[]>([]);
  const [addId, setAddId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const selected = stories.find((story) => story.id === selectedId) ?? null;

  async function loadItems(ids: number[]) {
    const next = ids.length ? await api.itemSelection(ids) : [];
    setItems(next);
    return next;
  }

  function activate(story: Story) {
    setSelectedId(story.id);
    setDraft({
      name: story.name,
      description: story.description,
      chapters: story.chapters.map((chapter) => ({ ...chapter })),
    });
    void loadItems(story.chapters.map((chapter) => chapter.item_id))
      .catch((error) => setMessage((error as Error).message));
  }

  async function beginFromIds(ids: number[], name = "") {
    const next = await loadItems(ids);
    setSelectedId(null);
    setDraft({
      name,
      description: "",
      chapters: next.map((item) => ({
        item_id: item.id,
        title: chapterTitle(item),
        start_s: 0,
        end_s: item.duration_s,
      })),
    });
    setMessage(null);
  }

  useEffect(() => {
    let alive = true;
    Promise.all([api.stories(), api.playbackQueues()])
      .then(async ([storyList, queueList]) => {
        if (!alive) return;
        setStories(storyList);
        setQueues(queueList);
        const requested = readStoryQueue(searchParams.get("queue"));
        if (requested.length) {
          await beginFromIds(requested, searchParams.get("name") || "New story");
        } else if (storyList[0]) {
          activate(storyList[0]);
        }
      })
      .catch((error) => { if (alive) setMessage((error as Error).message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
    // Initial URL seed only; editor state owns changes after opening.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const itemById = useMemo(
    () => new Map(items.map((item) => [item.id, item])),
    [items],
  );
  const duration = storyDuration(draft.chapters, items);

  function updateChapter(index: number, changes: Partial<StoryChapter>) {
    setDraft((current) => ({
      ...current,
      chapters: current.chapters.map((chapter, position) => (
        position === index ? { ...chapter, ...changes } : chapter
      )),
    }));
  }

  async function useQueue() {
    const queue = queues.find((entry) => entry.id === Number(selectedQueueId));
    if (!queue) return;
    try {
      await beginFromIds(queue.item_ids, queue.name);
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  async function addFavorite() {
    const id = Number(addId);
    if (!Number.isSafeInteger(id) || id < 1) {
      setMessage("Enter a valid favorite number.");
      return;
    }
    if (draft.chapters.some((chapter) => chapter.item_id === id)) {
      setMessage(`Favorite #${id} is already in this story.`);
      return;
    }
    try {
      const [item] = await api.itemSelection([id]);
      if (!item) {
        setMessage(`Favorite #${id} was not found.`);
        return;
      }
      setItems((current) => [...current, item]);
      setDraft((current) => ({
        ...current,
        chapters: [...current.chapters, {
          item_id: item.id,
          title: chapterTitle(item),
          start_s: 0,
          end_s: item.duration_s,
        }],
      }));
      setAddId("");
      setMessage(null);
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  function acceptSaved(story: Story) {
    setStories((current) => {
      const without = current.filter((entry) => entry.id !== story.id);
      return [story, ...without];
    });
    setSelectedId(story.id);
    setDraft({
      name: story.name,
      description: story.description,
      chapters: story.chapters.map((chapter) => ({ ...chapter })),
    });
  }

  async function persist() {
    const saved = selectedId == null
      ? await api.createStory(draft)
      : await api.updateStory(selectedId, draft);
    acceptSaved(saved);
    return saved;
  }

  async function save() {
    setBusy(true);
    setMessage("Saving story…");
    try {
      const saved = await persist();
      setMessage(`Saved “${saved.name}”.`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function render() {
    setBusy(true);
    setMessage("Saving edits and rendering locally with FFmpeg…");
    try {
      const saved = await persist();
      const rendered = await api.renderStory(saved.id);
      acceptSaved(rendered);
      setMessage("Story rendered. Your source favorites were not changed.");
    } catch (error) {
      setMessage(`Render failed: ${(error as Error).message}`);
      if (selectedId != null) {
        api.stories().then(setStories).catch(() => {});
      }
    } finally {
      setBusy(false);
    }
  }

  async function removeStory() {
    if (selectedId == null || !window.confirm("Delete this story plan? Source favorites and rendered media are never edited by this action.")) return;
    setBusy(true);
    try {
      await api.deleteStory(selectedId);
      const remaining = stories.filter((story) => story.id !== selectedId);
      setStories(remaining);
      if (remaining[0]) activate(remaining[0]);
      else {
        setSelectedId(null);
        setDraft(EMPTY_STORY);
        setItems([]);
      }
      setMessage("Story plan deleted.");
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <div className="mx-auto max-w-7xl space-y-3 px-4 py-8"><Skeleton className="h-24" /><Skeleton className="h-[32rem]" /></div>;
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-7xl px-4 py-8">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Cut a path through the archive</p>
            <h1 className="mt-1 text-2xl font-semibold text-ink">Story Builder</h1>
            <p className="mt-1 max-w-2xl text-sm text-ink-dim">Arrange, trim, and render favorites into a personal MP4. Editing a story never changes the source media.</p>
          </div>
          <Button variant="ghost" onClick={() => { setSelectedId(null); setDraft(EMPTY_STORY); setItems([]); setMessage(null); }}>
            <Plus size={16} /> New story
          </Button>
        </div>

        <div className="grid gap-5 lg:grid-cols-[15rem_minmax(0,1fr)]">
          <aside className="space-y-4 lg:self-start">
            <section className="rounded-[var(--radius-media)] border border-line bg-surface p-2">
              <p className="px-3 py-2 text-xs font-medium uppercase tracking-wider text-ink-faint">Saved stories</p>
              {stories.length ? (
                <ol className="space-y-1">
                  {stories.map((story) => (
                    <li key={story.id}>
                      <button type="button" onClick={() => activate(story)} className={`w-full rounded-[var(--radius-control)] px-3 py-3 text-left text-sm transition ${story.id === selectedId ? "bg-elevated text-ink" : "text-ink-dim hover:bg-elevated/60 hover:text-ink"}`}>
                        <span className="block truncate font-medium">{story.name}</span>
                        <span className="mt-1 block text-xs text-ink-faint">{story.chapters.length} chapters{story.rendered_url ? " · rendered" : ""}</span>
                      </button>
                    </li>
                  ))}
                </ol>
              ) : <p className="px-3 pb-3 text-sm text-ink-dim">No saved stories yet.</p>}
            </section>
            <section className="rounded-[var(--radius-media)] border border-line bg-surface p-4">
              <label className="text-xs text-ink-dim">Start from a Gallery queue
                <select value={selectedQueueId} onChange={(event) => setSelectedQueueId(event.target.value)} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink">
                  <option value="">Choose a queue…</option>
                  {queues.map((queue) => <option key={queue.id} value={queue.id}>{queue.name} · {queue.item_ids.length}</option>)}
                </select>
              </label>
              <Button variant="ghost" size="sm" className="mt-2 w-full" disabled={!selectedQueueId} onClick={() => void useQueue()}>
                Use this queue
              </Button>
            </section>
          </aside>

          <main className="min-w-0">
            <section className="rounded-[var(--radius-media)] border border-line bg-surface p-5">
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="text-xs text-ink-dim">Story name
                  <input value={draft.name} maxLength={80} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} placeholder="Weekend recipes" className="mt-1 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink placeholder:text-ink-faint" />
                </label>
                <label className="text-xs text-ink-dim">Description
                  <input value={draft.description} maxLength={500} onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))} placeholder="Why this collection matters" className="mt-1 h-10 w-full rounded-[var(--radius-control)] border border-line bg-elevated px-3 text-sm text-ink placeholder:text-ink-faint" />
                </label>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
                <p className="text-sm text-ink-dim">{draft.chapters.length} chapters · {formatDuration(duration)}</p>
                <div className="flex flex-wrap gap-2">
                  {selectedId != null && <Button variant="danger" size="sm" disabled={busy} onClick={() => void removeStory()}><Trash size={15} />Delete</Button>}
                  <Button variant="ghost" size="sm" disabled={busy || !draft.name.trim() || !draft.chapters.length} onClick={() => void save()}><FloppyDisk size={15} />Save</Button>
                  <Button size="sm" disabled={busy || !draft.name.trim() || !draft.chapters.length} onClick={() => void render()}><FilmReel size={15} />{busy ? "Working…" : "Render MP4"}</Button>
                </div>
              </div>
              {message && <p role="status" className="mt-3 text-sm text-ink-dim">{message}</p>}
            </section>

            {selected?.rendered_url && (
              <section className="mt-5 grid gap-4 rounded-[var(--radius-media)] border border-ok/30 bg-surface p-5 md:grid-cols-[12rem_minmax(0,1fr)] md:items-center">
                <video src={selected.rendered_url} controls preload="metadata" className="aspect-[9/16] max-h-72 w-full rounded-[var(--radius-control)] bg-black object-contain" />
                <div>
                  <p className="text-sm font-semibold text-ink">Rendered locally</p>
                  <p className="mt-1 text-sm text-ink-dim">This derived MP4 is normalized for vertical playback. The originals remain untouched.</p>
                  <a href={selected.rendered_url} download={`${selected.name}.mp4`} className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"><DownloadSimple size={16} />Download MP4</a>
                </div>
              </section>
            )}

            <section className="mt-5 rounded-[var(--radius-media)] border border-line bg-surface p-5">
              <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-ink">Chapters</h2>
                  <p className="mt-1 text-xs text-ink-dim">Order, label, and optionally trim each favorite.</p>
                </div>
                <div className="flex items-end gap-2">
                  <label className="text-xs text-ink-dim">Favorite #
                    <input value={addId} inputMode="numeric" onChange={(event) => setAddId(event.target.value)} className="mt-1 h-9 w-24 rounded-[var(--radius-control)] border border-line bg-elevated px-2 text-sm text-ink" />
                  </label>
                  <Button variant="ghost" size="sm" onClick={() => void addFavorite()}><Plus size={15} />Add</Button>
                </div>
              </div>
              {draft.chapters.length ? (
                <ol className="space-y-3">
                  {draft.chapters.map((chapter, index) => {
                    const item = itemById.get(chapter.item_id);
                    return (
                      <li key={chapter.item_id} className="grid gap-3 rounded-[var(--radius-control)] border border-line bg-elevated p-3 sm:grid-cols-[3rem_minmax(0,1fr)_7rem_7rem_auto] sm:items-end">
                        <div className="relative h-16 w-12 overflow-hidden rounded bg-canvas">
                          {item?.thumbnail_url ? <img src={item.thumbnail_url} alt="" className="h-full w-full object-cover" /> : <span aria-hidden className="flex h-full items-center justify-center text-ink-faint"><Scissors size={18} /></span>}
                          <span className="absolute bottom-0 right-0 bg-black/70 px-1 text-[10px] text-white">{index + 1}</span>
                        </div>
                        <label className="text-xs text-ink-dim">Chapter title
                          <input value={chapter.title} maxLength={120} onChange={(event) => updateChapter(index, { title: event.target.value })} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-surface px-2 text-sm text-ink" />
                          <Link to={`/?item=${chapter.item_id}&start_s=${chapter.start_s}`} className="mt-1 inline-block text-[11px] font-medium text-accent hover:underline">Preview in Feed</Link>
                        </label>
                        <label className="text-xs text-ink-dim">Start (seconds)
                          <input type="number" min="0" step="0.1" value={chapter.start_s} onChange={(event) => updateChapter(index, { start_s: Number(event.target.value) || 0 })} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-surface px-2 text-sm text-ink" />
                        </label>
                        <label className="text-xs text-ink-dim">End (optional)
                          <input type="number" min="0" step="0.1" value={chapter.end_s ?? ""} onChange={(event) => updateChapter(index, { end_s: event.target.value === "" ? null : Number(event.target.value) })} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-surface px-2 text-sm text-ink" />
                        </label>
                        <div className="flex gap-1">
                          <Button variant="ghost" size="xs" aria-label={`Move chapter ${index + 1} up`} disabled={index === 0} onClick={() => setDraft((current) => ({ ...current, chapters: moveStoryChapter(current.chapters, index, -1) }))}><ArrowUp size={14} /></Button>
                          <Button variant="ghost" size="xs" aria-label={`Move chapter ${index + 1} down`} disabled={index === draft.chapters.length - 1} onClick={() => setDraft((current) => ({ ...current, chapters: moveStoryChapter(current.chapters, index, 1) }))}><ArrowDown size={14} /></Button>
                          <Button variant="danger" size="xs" aria-label={`Remove chapter ${index + 1}`} onClick={() => setDraft((current) => ({ ...current, chapters: current.chapters.filter((_, position) => position !== index) }))}><Trash size={14} /></Button>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <EmptyState icon={<Scissors size={34} />} title="Add a first chapter" hint={<>Start from a saved Gallery queue, or enter a favorite number above. <Link to="/gallery" className="text-accent hover:underline">Open Gallery</Link></>} />
              )}
            </section>
          </main>
        </div>
      </div>
    </div>
  );
}

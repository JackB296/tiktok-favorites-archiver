import { useEffect, useId, useRef, useState } from "react";
import { ChatCircle, X } from "@phosphor-icons/react";
import { Link } from "react-router-dom";
import type { Item, SourceComment, SourceMetadataDetails } from "../lib/types";
import { api } from "../lib/api";
import { commentSnapshotSummary, commentThreads, savedCommentsSummary } from "../lib/commentsPresentation";
import { Dialog, Skeleton } from "./ui";

function commentDate(timestamp: number | undefined) {
  if (!timestamp) return null;
  const date = new Date(timestamp * 1000);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString();
}

function CommentCard({ comment, reply = false }: { comment: SourceComment; reply?: boolean }) {
  const posted = commentDate(comment.timestamp);
  const author = comment.author_username ? `@${comment.author_username}` : (comment.author || "Unknown commenter");
  return <article className={reply ? "ml-5 border-l-2 border-line pl-3" : "rounded-[var(--radius-control)] bg-elevated p-3"}>
    <p className="text-xs font-semibold text-ink-dim">
      {author}
      {comment.like_count != null ? ` · ${comment.like_count.toLocaleString()} likes` : ""}
    </p>
    {comment.text && <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{comment.text}</p>}
    {posted && <p className="mt-1 text-[11px] text-ink-faint">{posted}</p>}
  </article>;
}

export function SavedComments({ comments, reported }: { comments: SourceComment[]; reported: number | null }) {
  const threads = commentThreads(comments);
  return <>
    <p className="text-xs text-ink-faint">{savedCommentsSummary(comments.length, reported)}</p>
    {threads.length > 0 && <ul className="mt-3 space-y-3">
      {threads.map(({ comment, replies }, index) => <li key={comment.id ?? index} className="space-y-2">
        <CommentCard comment={comment} />
        {replies.map((reply, replyIndex) => <CommentCard key={reply.id ?? replyIndex} comment={reply} reply />)}
      </li>)}
    </ul>}
  </>;
}

export function CommentHistory({ details, reported }: { details: SourceMetadataDetails; reported: number | null }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const snapshots = details.comment_snapshots ?? [];
  const active = snapshots.find((snapshot) => snapshot.id === selectedId) ?? snapshots[0] ?? null;
  const comments = active?.comments ?? details.comments;
  const captured = active ? new Date(active.captured_at) : null;
  const capturedLabel = captured && !Number.isNaN(captured.getTime()) ? captured.toLocaleString() : null;

  return <>
    {snapshots.length > 0 && <div className="mb-3 rounded-[var(--radius-control)] border border-line bg-elevated p-3">
      <label className="block text-xs font-medium text-ink-dim" htmlFor="comment-snapshot">Saved snapshot</label>
      <select id="comment-snapshot" value={active?.id ?? ""} onChange={(event) => setSelectedId(Number(event.target.value))} className="mt-1 h-9 w-full rounded-[var(--radius-control)] border border-line bg-surface px-2 text-sm text-ink">
        {snapshots.map((snapshot, index) => <option key={snapshot.id} value={snapshot.id}>
          {index === 0 ? "Latest - " : ""}{new Date(snapshot.captured_at).toLocaleString()} ({snapshot.saved_count.toLocaleString()} saved)
        </option>)}
      </select>
      <p className="mt-2 text-xs text-ink-faint">{capturedLabel ? `Captured ${capturedLabel}. ` : ""}{commentSnapshotSummary(active?.changes ?? { added: 0, removed: 0, changed: 0 })}.</p>
    </div>}
    <SavedComments comments={comments} reported={active?.reported_count ?? reported} />
  </>;
}

export function CommentsDialog({ item, onClose }: { item: Item; onClose: () => void }) {
  const titleId = useId();
  const closeRef = useRef<HTMLButtonElement>(null);
  const [details, setDetails] = useState<SourceMetadataDetails | null>(null);
  const [loading, setLoading] = useState(item.source_info_status === "ok");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (item.source_info_status !== "ok") return;
    let alive = true;
    api.itemSourceMetadata(item.id)
      .then((value) => { if (alive) setDetails(value); })
      .catch((reason) => { if (alive) setError((reason as Error).message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [item.id, item.source_info_status]);

  return <Dialog labelledBy={titleId} onClose={onClose} initialFocusRef={closeRef} className="bg-black/70">
    <div className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto rounded-[var(--radius-media)] border border-line bg-surface p-5 shadow-2xl">
      <div className="flex items-start justify-between gap-4">
        <div><p className="tabular text-xs text-ink-faint">Favorite #{item.id}</p><h2 id={titleId} className="mt-1 flex items-center gap-2 text-lg font-semibold text-ink"><ChatCircle size={20} /> Comments</h2></div>
        <button ref={closeRef} type="button" onClick={onClose} aria-label="Close comments" className="rounded-[var(--radius-control)] p-2 text-ink-dim hover:bg-elevated hover:text-ink"><X size={18} /></button>
      </div>
      {item.caption && <p className="mt-3 line-clamp-2 text-sm text-ink-dim">{item.caption}</p>}
      <div className="mt-4 border-t border-line pt-4">
        {loading ? <div className="space-y-3" aria-label="Loading saved comments"><Skeleton className="h-16" /><Skeleton className="h-20" /></div>
          : error ? <p role="alert" className="rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-sm text-bad">Could not load saved comments: {error}</p>
          : details && (details.comments.length > 0 || details.comment_snapshots?.length > 0 || item.comments_status === "ok") ? <CommentHistory details={details} reported={item.comment_count} />
          : <div className="rounded-[var(--radius-control)] border border-line bg-elevated p-4 text-sm text-ink-dim"><p>Comments have not been archived for this post yet.</p><p className="mt-2">Run the <Link to="/sync" className="font-medium text-ink underline underline-offset-2">Media sidecars</Link> phase from Sync to fetch public comments that TikTok makes available.</p></div>}
      </div>
    </div>
  </Dialog>;
}

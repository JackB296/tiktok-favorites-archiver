import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowClockwise, ArrowSquareOut, CaretDown, MusicNotes } from "@phosphor-icons/react";
import type { Item, SourceComment, SourceMetadataDetails } from "../lib/types";
import { api } from "../lib/api";
import { commentThreads } from "../lib/commentsPresentation";
import { captionParts, cleanMetadataText, hashtagGalleryUrl, postBlurb } from "../lib/captionPresentation.js";
import { isSafeHttpUrl } from "../lib/format";
import { primarySongUrl, songLabel } from "../lib/songLinks.js";
import { Skeleton, cx } from "./ui";

/** Comments already fetched this session. A post's archived comments do not
 * change while you watch, so each one is only ever loaded once. */
const cache = new Map<number, SourceComment[]>();

/** A comment with dozens of replies would bury the conversation, so replies
 * open a handful at a time. Top-level comments simply run to the bottom. */
const REPLY_PAGE = 5;

function CommentBody({ comment }: { comment: SourceComment }) {
  const who = comment.author_username ? `@${comment.author_username}` : (comment.author || "Unknown commenter");
  return (
    <div className="min-w-0 flex-1">
      <p className="truncate text-[11px] font-medium text-ink-dim">{who}</p>
      {comment.text && <p className="mt-0.5 whitespace-pre-wrap break-words text-[12.5px] leading-[1.45] text-ink">{comment.text}</p>}
      {comment.like_count != null && comment.like_count > 0 && (
        <p className="tabular mt-0.5 text-[10.5px] text-ink-dim">{comment.like_count.toLocaleString()} likes</p>
      )}
    </div>
  );
}

function Thread({ comment, replies }: { comment: SourceComment; replies: SourceComment[] }) {
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState(REPLY_PAGE);
  const visible = replies.slice(0, shown);

  function toggle() {
    setOpen((value) => {
      if (value) setShown(REPLY_PAGE);   // reopening starts from the top again
      return !value;
    });
  }

  return (
    <li className="py-2.5">
      <article className="flex gap-2.5"><CommentBody comment={comment} /></article>
      {replies.length > 0 && (
        <div className="mt-1.5 pl-3">
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            className="inline-flex items-center gap-1.5 rounded text-[11px] font-medium text-ink-dim transition hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span aria-hidden className="h-px w-4 bg-line" />
            {open ? "Hide" : "View"} {replies.length} {replies.length === 1 ? "reply" : "replies"}
            <CaretDown size={11} weight="bold" className={cx("transition", open && "rotate-180")} />
          </button>
          {open && (
            <div className="mt-1.5 border-l-2 border-line pl-3">
              <ul className="space-y-2.5">
                {visible.map((reply, index) => (
                  <li key={reply.id ?? index} className="flex gap-2.5"><CommentBody comment={reply} /></li>
                ))}
              </ul>
              {replies.length > visible.length && (
                <button
                  type="button"
                  onClick={() => setShown((count) => count + REPLY_PAGE)}
                  className="mt-2 text-[11px] font-semibold text-ink-dim underline decoration-line underline-offset-[3px] transition hover:text-ink hover:decoration-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                >
                  View more · {(replies.length - visible.length).toLocaleString()} left
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function Blurb({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  // Four lines is a comfortable read; hashtag-stuffed posts run far past it.
  const long = text.length > 170;
  return (
    <>
      <p className={cx("whitespace-pre-wrap break-words text-[14.5px] leading-[1.5] text-ink", !expanded && long && "line-clamp-4")}>
        {captionParts(text).map((part, index) => part.hashtag ? (
          <Link key={`${part.text}-${index}`} to={hashtagGalleryUrl(part.hashtag)} title={`Show all favorites tagged ${part.hashtag}`} className="font-medium text-accent underline decoration-transparent underline-offset-2 transition hover:decoration-accent">{part.text}</Link>
        ) : <span key={`${part.text}-${index}`}>{part.text}</span>)}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="mt-1 text-[12px] font-semibold text-ink-dim underline decoration-line underline-offset-[3px] transition hover:text-ink hover:decoration-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          {expanded ? "View less" : "View more"}
        </button>
      )}
    </>
  );
}

/**
 * Everything about a post that is not the picture: creator, song, the post's
 * text, and its archived comments behind a dropdown.
 *
 * Nothing is fetched until the comments are actually opened, and only the
 * active post fetches at all — the Feed keeps several posts mounted, and a
 * stack of comment lists behind blurred glass is work nobody is looking at.
 */
export function PostDetailsPanel({ item, active, open, onToggle }: { item: Item; active: boolean; open: boolean; onToggle: () => void }) {
  const listRef = useRef<HTMLDivElement>(null);
  const author = cleanMetadataText(item.author);
  const blurb = postBlurb(item.caption, item.description);

  const [comments, setComments] = useState<SourceComment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // A new post starts at the top of its own comments.
  useEffect(() => {
    setError(null);
    setComments(cache.get(item.id) ?? null);
    listRef.current?.scrollTo({ top: 0 });
  }, [item.id]);

  useEffect(() => {
    if (!open || !active || comments !== null) return;
    if (item.source_info_status !== "ok") { setComments([]); return; }
    let alive = true;
    api.itemSourceMetadata(item.id)
      .then((details: SourceMetadataDetails) => {
        cache.set(item.id, details.comments);
        if (alive) setComments(details.comments);
      })
      .catch((reason) => { if (alive) setError((reason as Error).message); });
    return () => { alive = false; };
  }, [open, active, comments, item.id, item.source_info_status]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const result = await api.refreshItemComments(item.id);
      cache.set(item.id, result.comments);
      setComments(result.comments);
      setError(null);
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setRefreshing(false);
    }
  }, [item.id]);

  const threads = comments ? commentThreads(comments) : [];

  return (
    <div className={cx(
      "flex min-h-0 flex-col rounded-[var(--radius-media)] border border-white/15 bg-black/75 text-ink shadow-2xl shadow-black/60 backdrop-blur-2xl",
      open ? "h-full" : "max-h-full",
    )}>
      <div className="flex-none border-b border-white/10 px-5 py-4">
        {author && (
          <div className="mb-2.5 flex min-w-0 items-center gap-2">
            <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-dim">Creator</span>
            {item.creator ? (
              <Link to={`/gallery?creator=${encodeURIComponent(item.creator.key)}`} title="Show every archived video from this creator" className="truncate text-[15px] font-semibold text-ink underline decoration-line underline-offset-2 hover:decoration-ink">{author}</Link>
            ) : (
              <span className="truncate text-[15px] font-semibold text-ink">{author}</span>
            )}
          </div>
        )}
        {item.song && (
          <div className="mb-2.5 flex min-w-0 items-center gap-2">
            <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-dim">Song</span>
            {item.song.id != null ? (
              <Link to={`/gallery?song=${item.song.id}`} title="Show every archived video using this song" className="inline-flex min-w-0 items-center gap-1.5 text-[14.5px] font-semibold text-ink underline decoration-line underline-offset-2 hover:decoration-ink">
                <MusicNotes size={14} weight="fill" className="shrink-0" /><span className="truncate">{songLabel(item.song)}</span>
              </Link>
            ) : (
              <span className="truncate text-[14.5px] font-semibold text-ink">{songLabel(item.song)}</span>
            )}
            <a href={primarySongUrl(item.song)} target="_blank" rel="noreferrer" title="Find this song online" aria-label={`Find ${songLabel(item.song)} online`} className="shrink-0 rounded-full p-1 text-ink-dim hover:bg-white/10 hover:text-ink"><ArrowSquareOut size={13} /></a>
          </div>
        )}
        {blurb && <Blurb text={blurb} />}
        <div className="tabular mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-dim">
          <span>#{item.id}</span>
          {item.view_count != null && <span>· {item.view_count.toLocaleString()} views</span>}
          {isSafeHttpUrl(item.link) && (
            <a href={item.link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded px-1 py-0.5 underline decoration-line underline-offset-2 transition hover:text-ink hover:decoration-ink">
              <ArrowSquareOut size={11} />TikTok
            </a>
          )}
        </div>
      </div>

      {/* The dropdown and its refresh share one line. */}
      <div className="flex flex-none items-center justify-between gap-2 px-5 pb-2.5 pt-3.5">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-controls={`comments-${item.id}`}
          className="flex items-center gap-2 text-left text-[11px] font-semibold uppercase tracking-[0.14em] text-ink-dim transition hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Comments
          {item.comment_count != null && <span className="tabular font-normal tracking-normal text-ink-dim/70">{item.comment_count.toLocaleString()}</span>}
          <CaretDown size={12} weight="bold" className={cx("transition", open && "rotate-180")} />
        </button>
        {open && (
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={refreshing}
            title="Fetch this post's comments from TikTok again"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-[11px] font-medium text-ink-dim transition hover:bg-white/10 hover:text-ink disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <ArrowClockwise size={11} weight="bold" className={cx(refreshing && "animate-spin")} />
            {refreshing ? "Checking…" : "Latest"}
          </button>
        )}
      </div>

      {open && (
        <div
          ref={listRef}
          id={`comments-${item.id}`}
          data-comment-scroll="true"
          tabIndex={0}
          role="region"
          aria-label={`Comments on favorite #${item.id}`}
          className="no-scrollbar min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-4 focus-visible:outline focus-visible:-outline-offset-2 focus-visible:outline-accent"
        >
          {error && <p role="alert" className="rounded-[var(--radius-control)] border border-bad/40 bg-bad/10 p-3 text-[12.5px] text-bad">Could not load comments: {error}</p>}
          {!error && comments === null && (
            <div className="space-y-2.5" aria-label="Loading comments"><Skeleton className="h-12" /><Skeleton className="h-16" /><Skeleton className="h-12" /></div>
          )}
          {!error && comments !== null && comments.length === 0 && (
            <div className="rounded-[var(--radius-control)] border border-white/10 bg-white/5 p-3.5 text-[12.5px] leading-relaxed text-ink-dim">
              <p>No comments were archived for this post.</p>
              <p className="mt-2">Use Latest to fetch them now, or run the <Link to="/sync" className="font-medium text-ink underline underline-offset-2">Media sidecars</Link> phase from Sync for the whole library.</p>
            </div>
          )}
          {!error && threads.length > 0 && (
            <ul className="divide-y divide-line/50">
              {threads.map(({ comment, replies }, index) => (
                <Thread key={comment.id ?? index} comment={comment} replies={replies} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

import type { SourceComment } from "./types";

export interface CommentThread {
  comment: SourceComment;
  replies: SourceComment[];
}

function isRoot(parent: string | undefined) {
  return parent == null || parent === "" || parent === "0" || parent === "root";
}

/** Preserve TikTok's saved order while ensuring replies remain visible even
 * when the extractor returned them before their top-level comment. */
export function commentThreads(comments: SourceComment[]): CommentThread[] {
  const ids = new Set(comments.map((comment) => comment.id).filter(Boolean));
  const roots = comments.filter((comment) => isRoot(comment.parent));
  const orphans = comments.filter((comment) => !isRoot(comment.parent) && !ids.has(comment.parent));
  return [...roots, ...orphans].map((comment) => ({
    comment,
    replies: comment.id
      ? comments.filter((candidate) => candidate.parent === comment.id)
      : [],
  }));
}

export function savedCommentsSummary(saved: number, reported: number | null | undefined) {
  if (saved === 0) {
    return reported
      ? `TikTok reported ${reported.toLocaleString()} comments, but none were available to save.`
      : "No public comments were reported.";
  }
  if (reported && saved < reported) {
    return `Showing ${saved.toLocaleString()} saved of ${reported.toLocaleString()} reported comments.`;
  }
  return `${saved.toLocaleString()} saved comment${saved === 1 ? "" : "s"}.`;
}

export function commentSnapshotSummary(changes: { added: number; removed: number; changed: number }) {
  const parts = [
    changes.added ? `${changes.added.toLocaleString()} new` : "",
    changes.removed ? `${changes.removed.toLocaleString()} unavailable` : "",
    changes.changed ? `${changes.changed.toLocaleString()} updated` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : "No changes from the previous snapshot";
}

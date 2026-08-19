"""Fast global browsing over normalized local comment snapshots."""
from core import search_query


def _field_clauses(parsed):
    clauses = []
    params = []
    text_tokens = list(parsed.terms)
    text_tokens.extend(parsed.fields.get("comment", ()))
    text_tokens.extend(parsed.fields.get("text", ()))
    for token in parsed.fields.get("author", ()):
        clauses.append("LOWER(COALESCE(ce.author_username, ce.author, '')) = LOWER(?)")
        params.append(token.value.lstrip("@"))
    numeric = {
        "views": "item.view_count",
        "likes": "ce.like_count",
        "post_comments": "item.comment_count",
    }
    for field, column in numeric.items():
        for token in parsed.fields.get(field, ()):
            operator, value = search_query.comparison(token.value)
            clauses.append(f"{column} {operator} ?")
            params.append(value)
    for token in parsed.fields.get("posted", ()):
        if not token.value[:4].isdigit() or len(token.value) not in (4, 7, 10):
            raise ValueError("posted must be YYYY, YYYY-MM, or YYYY-MM-DD")
        clauses.append("item.source_posted_at LIKE ?")
        params.append(token.value + "%")
    return text_tokens, clauses, params


def search(conn, query, *, include_history=False, limit=50, cursor=None):
    """Search saved comment text/authors; latest snapshots are the default."""
    limit = max(1, min(int(limit), 100))
    parsed = search_query.parse(query)
    text_tokens, clauses, params = _field_clauses(parsed)
    match = search_query.fts_query(text_tokens)
    if match:
        head = (
            "SELECT ce.*, cs.captured_at, item.caption, item.author AS item_author, "
            "CASE WHEN cs.id = (SELECT MAX(newest.id) FROM comment_snapshot newest "
            "WHERE newest.item_id = ce.item_id) THEN 1 ELSE 0 END AS latest "
            "FROM comment_entry_search ces "
            "JOIN comment_entry ce ON ce.id = ces.rowid "
            "JOIN comment_snapshot cs ON cs.id = ce.snapshot_id "
            "JOIN item ON item.id = ce.item_id"
        )
        clauses.insert(0, "comment_entry_search MATCH ?")
        params.insert(0, match)
    else:
        head = (
            "SELECT ce.*, cs.captured_at, item.caption, item.author AS item_author, "
            "CASE WHEN cs.id = (SELECT MAX(newest.id) FROM comment_snapshot newest "
            "WHERE newest.item_id = ce.item_id) THEN 1 ELSE 0 END AS latest "
            "FROM comment_entry ce JOIN comment_snapshot cs ON cs.id = ce.snapshot_id "
            "JOIN item ON item.id = ce.item_id"
        )
    if not include_history:
        clauses.append(
            "ce.snapshot_id = (SELECT MAX(current.id) FROM comment_snapshot current "
            "WHERE current.item_id = ce.item_id)"
        )
    if cursor is not None:
        clauses.append("ce.id < ?")
        params.append(int(cursor))
    sql = head + (" WHERE " + " AND ".join(clauses) if clauses else "")
    rows = conn.execute(sql + " ORDER BY ce.id DESC LIMIT ?", (*params, limit)).fetchall()
    results = []
    for row in rows:
        entry = dict(row)
        entry["latest"] = bool(entry["latest"])
        root = entry["parent_key"] or entry["comment_key"]
        context = conn.execute(
            "SELECT author, author_username, text, like_count, comment_key, parent_key "
            "FROM comment_entry WHERE snapshot_id = ? AND id != ? "
            "AND (comment_key = ? OR parent_key = ? OR parent_key = ?) "
            "ORDER BY id LIMIT 8",
            (entry["snapshot_id"], entry["id"], root, root, entry["comment_key"]),
        ).fetchall()
        entry["thread_context"] = [dict(context_row) for context_row in context]
        results.append(entry)
    return {
        "results": results,
        "next_cursor": results[-1]["id"] if len(results) == limit else None,
        "include_history": bool(include_history),
    }

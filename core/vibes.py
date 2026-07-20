"""Explainable, dependency-free sparse text embeddings for archive discovery."""
import math
import re
import unicodedata
from collections import Counter


MAX_DOCUMENT_CHARS = 12000
MAX_QUERY_CHARS = 240
_WORD = re.compile(r"[^\W_][\w'-]*", re.UNICODE)
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "i", "in", "is", "it", "its", "of", "on", "or", "that", "the",
    "this", "to", "was", "we", "were", "with", "you", "your",
}


def _words(text):
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    words = [
        word.strip("_'-") for word in _WORD.findall(normalized)
    ]
    return [word for word in words if len(word) > 1 and word not in _STOP]


def _word_features(word):
    features = [word]
    if len(word) >= 4:
        padded = f"^{word}$"
        features.extend(f"~{padded[i:i + 3]}" for i in range(len(padded) - 2))
    return features


def _tokens(text):
    return _tokens_for_words(_words(text))


def _tokens_for_words(words):
    return [
        feature for word in words
        for feature in _word_features(word)
    ]


def documents(conn):
    rows = conn.execute(
        "SELECT i.id, i.caption, i.author, "
        "COALESCE(s.title, '') AS song_title, COALESCE(s.artist, '') AS song_artist, "
        "COALESCE((SELECT GROUP_CONCAT(a.text, ' ') FROM analysis_segment a "
        "WHERE a.item_id = i.id), '') AS analysis_text, "
        "COALESCE((SELECT GROUP_CONCAT(h.display_name, ' ') "
        "FROM item_hashtag ih JOIN hashtag h ON h.id = ih.hashtag_id "
        "WHERE ih.item_id = i.id), '') AS hashtag_text "
        "FROM item i LEFT JOIN song s ON s.id = i.song_id "
        "WHERE i.status IN ('done', 'expired') OR i.offloaded = 1 "
        "ORDER BY i.id"
    ).fetchall()
    result = []
    for row in rows:
        text = " ".join(
            value for value in (
                row["caption"], row["author"], row["song_title"],
                row["song_artist"], row["analysis_text"], row["hashtag_text"],
            ) if value
        )[:MAX_DOCUMENT_CHARS]
        words = _words(text)
        features = Counter(_tokens_for_words(words))
        if features:
            result.append({
                "id": row["id"],
                "text": text,
                "words": words,
                "features": features,
            })
    return result


def _rank(docs, query_text, limit, exclude_id=None):
    limit = int(limit)
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    query_features = Counter(_tokens(query_text))
    if not query_features:
        return []
    doc_features = [
        (doc, doc["features"], doc["words"])
        for doc in docs
    ]
    document_frequency = Counter()
    for _doc, features, _document_words in doc_features:
        document_frequency.update(features.keys())
    total = max(1, len(doc_features))

    def idf(feature):
        return math.log((1 + total) / (1 + document_frequency[feature])) + 1

    query_vector = {
        feature: (1 + math.log(count)) * idf(feature)
        for feature, count in query_features.items()
    }
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    ranked = []
    for doc, features, document_words in doc_features:
        if doc["id"] == exclude_id:
            continue
        dot = 0.0
        norm = 0.0
        for feature, count in features.items():
            weight = (1 + math.log(count)) * idf(feature)
            norm += weight * weight
            dot += weight * query_vector.get(feature, 0.0)
        score = dot / (query_norm * math.sqrt(norm)) if norm and query_norm else 0
        # Character features make nearby word forms discoverable, but tiny
        # accidental overlaps are noise rather than a useful "vibe" match.
        if score < 0.08:
            continue
        evidence = sorted(
            (
                feature for feature in query_features
                if not feature.startswith("~") and feature in features
            ),
            key=lambda feature: (-idf(feature), feature),
        )[:5]
        if not evidence:
            def trigram_overlap(word):
                return sum(
                    feature.startswith("~") and feature in query_features
                    for feature in _word_features(word)
                )

            evidence = [
                word for _overlap, word in sorted(
                    (
                        (trigram_overlap(word), word)
                        for word in set(document_words)
                    ),
                    key=lambda value: (-value[0], value[1]),
                )
                if _overlap
            ][:5]
        ranked.append({
            "item_id": doc["id"],
            "score": round(score, 4),
            "evidence": evidence,
        })
    ranked.sort(key=lambda result: (-result["score"], result["item_id"]))
    return ranked[:limit]


def search(conn, query, limit=24):
    if not isinstance(query, str):
        raise ValueError("query must be text")
    query = query.strip()
    if not 2 <= len(query) <= MAX_QUERY_CHARS:
        raise ValueError(f"query must be between 2 and {MAX_QUERY_CHARS} characters")
    return _rank(documents(conn), query, limit)


def related(conn, item_id, limit=24):
    docs = documents(conn)
    seed = next((doc for doc in docs if doc["id"] == int(item_id)), None)
    if seed is None:
        raise KeyError(item_id)
    return _rank(docs, seed["text"], limit, exclude_id=seed["id"])

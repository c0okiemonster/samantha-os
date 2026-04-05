"""Pure functions for the Memory Timeline UI.

Reads the existing memory tables and normalizes rows from six different
sources into a single unified entry shape. Supports soft-delete and
cursor pagination via an ISO 8601 `before` timestamp.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


VALID_TYPES: frozenset[str] = frozenset({
    "fact", "entity", "observation", "episode", "mood", "news",
})


# ─── Per-type projections ───────────────────────────────────────────────

def _fact_to_entry(row: sqlite3.Row) -> dict:
    subj = row["subject"] or "user"
    cat = row["category"] or ""
    key = row["key"] or ""
    return {
        "id": f"fact:{row['id']}",
        "type": "fact",
        "ts": _iso(row["learned_at"]),
        "title": f"{subj} · {cat} · {key}".strip(" ·"),
        "body": row["value"] or "",
        "meta": {
            "subject": subj,
            "category": cat,
            "confidence": row["confidence"],
            "source": row["source"],
        },
    }


def _entity_to_entry(row: sqlite3.Row) -> dict:
    etype = row["type"] or ""
    relation = row["relation"] or ""
    title = etype + (" · " + relation if relation else "")
    try:
        aliases = json.loads(row["aliases"] or "[]")
    except Exception:
        aliases = []
    return {
        "id": f"entity:{row['id']}",
        "type": "entity",
        "ts": _iso(row["first_mentioned"]),
        "title": title or "entity",
        "body": row["name"] or "",
        "meta": {
            "aliases": aliases,
            "last_mentioned": _iso(row["last_mentioned"]),
        },
    }


def _observation_to_entry(row: sqlite3.Row) -> dict:
    return {
        "id": f"observation:{row['id']}",
        "type": "observation",
        "ts": _iso(row["created_at"]),
        "title": "What she saw",
        "body": row["raw_description"] or "",
        "meta": {
            "spoken_text": row["spoken_text"] or "",
            "user_trigger": row["user_trigger"] or "",
        },
    }


def _episode_to_entry(row: sqlite3.Row) -> dict:
    try:
        topics = json.loads(row["topics"] or "[]")
    except Exception:
        topics = []
    try:
        threads = json.loads(row["unresolved_threads"] or "[]")
    except Exception:
        threads = []
    title = ", ".join(topics[:3]) if topics else "Conversation"
    if len(topics) > 3:
        title += f" (+{len(topics) - 3})"
    return {
        "id": f"episode:{row['id']}",
        "type": "episode",
        "ts": _iso(row["ended_at"]),
        "title": title,
        "body": row["summary"] or "",
        "meta": {
            "mood_arc": row["mood_arc"],
            "message_count": row["message_count"],
            "unresolved_threads": threads,
        },
    }


def _mood_to_entry(row: sqlite3.Row) -> dict:
    user_m = row["user_mood"] or "?"
    sam_m = row["samantha_mood"] or "?"
    return {
        "id": f"mood:{row['id']}",
        "type": "mood",
        "ts": _iso(row["timestamp"]),
        "title": f"{user_m} → {sam_m}",
        "body": row["trigger"] or "",
        "meta": {
            "sentiment": row["sentiment"],
            "intensity": row["intensity"],
            "note": row["note"],
        },
    }


def _news_to_entry(row: sqlite3.Row) -> dict:
    try:
        sources = json.loads(row["sources"] or "[]")
    except Exception:
        sources = []
    return {
        "id": f"news:{row['id']}",
        "type": "news",
        "ts": _iso(row["created_at"]),
        "title": "News digest",
        "body": row["summary"] or "",
        "meta": {
            "sentiment": row["sentiment"],
            "reaction": row["reaction"],
            "sources": sources,
        },
    }


# ─── Query config per type ──────────────────────────────────────────────

# type → (table, ts_column, projection_fn, column_list_for_select)
_PROJECTIONS: dict[str, tuple[str, str, Any, str]] = {
    "fact": (
        "facts", "learned_at", _fact_to_entry,
        "id, subject, category, key, value, confidence, source, learned_at",
    ),
    "entity": (
        "entities", "first_mentioned", _entity_to_entry,
        "id, name, type, relation, aliases, first_mentioned, last_mentioned",
    ),
    "observation": (
        "observations", "created_at", _observation_to_entry,
        "id, raw_description, spoken_text, user_trigger, created_at",
    ),
    "episode": (
        "episodes", "ended_at", _episode_to_entry,
        "id, summary, topics, mood_arc, message_count, ended_at, unresolved_threads",
    ),
    "mood": (
        "mood_log", "timestamp", _mood_to_entry,
        "id, user_mood, samantha_mood, trigger, timestamp, sentiment, intensity, note",
    ),
    "news": (
        "news_digests", "created_at", _news_to_entry,
        "id, summary, sentiment, reaction, sources, created_at",
    ),
}


# ─── Helpers ────────────────────────────────────────────────────────────

def _iso(s: Optional[str]) -> Optional[str]:
    """Coerce a sqlite TIMESTAMP (string) into a canonical ISO 8601 UTC string."""
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace(" ", "T"))
    except ValueError:
        return str(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# ─── Public API ─────────────────────────────────────────────────────────

def build_timeline(
    conn: sqlite3.Connection,
    types: set[str] | frozenset[str],
    limit: int = 100,
    before: Optional[str] = None,
) -> dict:
    """Run N queries (one per requested type), merge-sort by timestamp DESC,
    return up to `limit` entries plus a pagination cursor.

    `before` is an ISO 8601 string; rows with ts strictly less than `before`
    are returned (used for "load older" pagination).

    Raises ValueError if `types` contains an unknown type name.
    """
    if not types:
        return {"entries": [], "has_more": False, "next_before": None}

    unknown = set(types) - VALID_TYPES
    if unknown:
        raise ValueError(f"Unknown entry types: {sorted(unknown)}")

    conn.row_factory = sqlite3.Row

    collected: list[dict] = []
    for type_name in types:
        table, ts_col, projection, col_list = _PROJECTIONS[type_name]
        sql = (
            f"SELECT {col_list} FROM {table} "
            f"WHERE deleted_at IS NULL "
            f"AND (? IS NULL OR {ts_col} < ?) "
            f"ORDER BY {ts_col} DESC "
            f"LIMIT ?"
        )
        rows = conn.execute(sql, (before, before, limit + 1)).fetchall()
        for row in rows:
            collected.append(projection(row))

    # Merge sort by ts desc. Rows with None ts sink to the end.
    collected.sort(key=lambda e: e["ts"] or "", reverse=True)

    has_more = len(collected) > limit
    entries = collected[:limit]
    next_before: Optional[str] = None
    if has_more and entries:
        next_before = entries[-1]["ts"]

    return {
        "entries": entries,
        "has_more": has_more,
        "next_before": next_before,
    }


# ─── Soft delete / restore ──────────────────────────────────────────────

# type → table (for delete/restore; we don't need the projection here)
_TABLE_FOR_TYPE: dict[str, str] = {
    t: _PROJECTIONS[t][0] for t in VALID_TYPES
}


def _check_type(entry_type: str) -> str:
    if entry_type not in VALID_TYPES:
        raise ValueError(f"Unknown entry type: {entry_type!r}")
    return _TABLE_FOR_TYPE[entry_type]


def soft_delete_entry(
    conn: sqlite3.Connection,
    entry_type: str,
    entry_id: int,
) -> bool:
    """Set deleted_at on the target row. Returns True if a row was updated,
    False if the id did not exist OR was already soft-deleted. Raises
    ValueError for unknown type."""
    table = _check_type(entry_type)
    cur = conn.execute(
        f"UPDATE {table} SET deleted_at = CURRENT_TIMESTAMP "
        f"WHERE id = ? AND deleted_at IS NULL",
        (entry_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def restore_entry(
    conn: sqlite3.Connection,
    entry_type: str,
    entry_id: int,
) -> bool:
    """Clear deleted_at on the target row. Returns True if a row was updated,
    False if the id did not exist OR was not soft-deleted. Raises ValueError
    for unknown type."""
    table = _check_type(entry_type)
    cur = conn.execute(
        f"UPDATE {table} SET deleted_at = NULL "
        f"WHERE id = ? AND deleted_at IS NOT NULL",
        (entry_id,),
    )
    conn.commit()
    return cur.rowcount > 0

"""
Samantha OS — Notes & Memory Integration
Local SQLite database for persistent notes, reminders, and contextual memory.
This gives Samantha actual long-term memory between sessions.
"""

from __future__ import annotations
import os
import json
import sqlite3
import logging
from datetime import datetime

from integrations import BaseIntegration, IntegrationAction

logger = logging.getLogger("samantha.notes")


class NotesIntegration(BaseIntegration):
    name = "notes"
    display_name = "Notes & Memory"
    description = "Save notes, reminders, and remember things between sessions"
    icon = "📝"
    requires_auth = False

    def __init__(self):
        super().__init__()
        self.db_path: str = "config/samantha_memory.db"
        self.conn: sqlite3.Connection | None = None

    async def initialize(self, config: dict) -> bool:
        self.db_path = config.get("db_path", self.db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        logger.info(f"Notes DB: {self.db_path}")
        return True

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                remind_at TIMESTAMP,
                completed INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT NOT NULL,
                source TEXT DEFAULT 'conversation',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category);
            CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(completed, remind_at);
            CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
        """)

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="save_note",
                description="Save a note or thought",
                keywords=["note", "save", "write down", "remember this", "jot down"],
                parameters=["content", "category"],
                examples=["Make a note: call the dentist", "Remember that the meeting is at 3pm"],
            ),
            IntegrationAction(
                name="search_notes",
                description="Search saved notes",
                keywords=["notes", "what did I", "find note", "search notes"],
                parameters=["query"],
                examples=["What notes do I have?", "Find my notes about the project"],
            ),
            IntegrationAction(
                name="set_reminder",
                description="Set a reminder",
                keywords=["remind me", "reminder", "don't let me forget", "alarm"],
                parameters=["content", "remind_at"],
                examples=["Remind me to call John at 3pm", "Remind me to buy milk"],
            ),
            IntegrationAction(
                name="check_reminders",
                description="Check pending reminders",
                keywords=["reminders", "what should I", "pending", "to do", "tasks"],
                examples=["Any reminders?", "What's on my to-do list?"],
            ),
            IntegrationAction(
                name="remember",
                description="Store a fact for long-term memory",
                keywords=["remember that", "my favorite", "I like", "I prefer", "I am", "I live"],
                parameters=["key", "value"],
                examples=["Remember that my favorite color is blue", "I prefer tea over coffee"],
            ),
            IntegrationAction(
                name="recall",
                description="Recall a stored fact",
                keywords=["what's my", "do you remember", "what did I tell you"],
                parameters=["key"],
                examples=["What's my favorite color?", "Do you remember where I work?"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        handlers = {
            "save_note": self._save_note,
            "search_notes": self._search_notes,
            "set_reminder": self._set_reminder,
            "check_reminders": self._check_reminders,
            "remember": self._remember,
            "recall": self._recall,
        }
        handler = handlers.get(action_name)
        if not handler:
            return {"error": f"Unknown action: {action_name}"}
        return handler(params)

    def _save_note(self, params: dict) -> dict:
        content = params.get("content", "")
        category = params.get("category", "general")
        tags = json.dumps(params.get("tags", []))
        if not content:
            return {"error": "No content to save"}
        cur = self.conn.execute(
            "INSERT INTO notes (content, category, tags) VALUES (?, ?, ?)",
            (content, category, tags)
        )
        self.conn.commit()
        return {"saved": True, "id": cur.lastrowid, "content": content}

    def _search_notes(self, params: dict) -> dict:
        query = params.get("query", "")
        if query:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE content LIKE ? ORDER BY created_at DESC LIMIT 10",
                (f"%{query}%",)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM notes ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        return {"notes": [dict(r) for r in rows]}

    def _set_reminder(self, params: dict) -> dict:
        content = params.get("content", "")
        remind_at = params.get("remind_at")
        if not content:
            return {"error": "No reminder content"}
        self.conn.execute(
            "INSERT INTO reminders (content, remind_at) VALUES (?, ?)",
            (content, remind_at)
        )
        self.conn.commit()
        return {"set": True, "content": content, "remind_at": remind_at}

    def _check_reminders(self, params: dict) -> dict:
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE completed = 0 ORDER BY remind_at ASC LIMIT 20"
        ).fetchall()
        return {"reminders": [dict(r) for r in rows]}

    def _remember(self, params: dict) -> dict:
        key = params.get("key", "")
        value = params.get("value", "")
        if not key or not value:
            return {"error": "Need both key and value"}
        self.conn.execute(
            "INSERT OR REPLACE INTO memories (key, value, updated_at) VALUES (?, ?, ?)",
            (key.lower(), value, datetime.now().isoformat())
        )
        self.conn.commit()
        return {"remembered": True, "key": key, "value": value}

    def _recall(self, params: dict) -> dict:
        key = params.get("key", "")
        row = self.conn.execute(
            "SELECT * FROM memories WHERE key LIKE ?", (f"%{key.lower()}%",)
        ).fetchone()
        if row:
            return {"found": True, "key": row["key"], "value": row["value"]}
        return {"found": False, "key": key}

    async def get_proactive_updates(self) -> list[dict] | None:
        now = datetime.now().isoformat()
        rows = self.conn.execute(
            "SELECT * FROM reminders WHERE completed = 0 AND remind_at <= ? AND remind_at IS NOT NULL",
            (now,)
        ).fetchall()
        if not rows:
            return None
        updates = []
        for r in rows:
            updates.append({
                "type": "card",
                "title": "Reminder",
                "body": r["content"],
                "integration": self.name,
            })
            self.conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (r["id"],))
        self.conn.commit()
        return updates

    def get_context_for_llm(self) -> str | None:
        # Inject all memories into context
        rows = self.conn.execute("SELECT key, value FROM memories LIMIT 50").fetchall()
        if not rows:
            return "You can save notes, set reminders, and remember facts about the user."
        facts = "; ".join(f"{r['key']}: {r['value']}" for r in rows)
        return f"Things you remember about the user: {facts}. You can also save notes and set reminders."

    async def shutdown(self):
        if self.conn:
            self.conn.close()

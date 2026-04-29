"""SQLite state manager for tracking Trello validation card status."""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "trello_state.db"


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


class TrelloState:
    """Tracks trello_validation_cards rows in a local SQLite database."""

    def __init__(self, db_path=None):
        self._db_path = str(db_path or os.environ.get("TRELLO_STATE_DB", _DEFAULT_DB_PATH))
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trello_validation_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL UNIQUE,
                    card_id TEXT NOT NULL UNIQUE,
                    blog_title TEXT NOT NULL,
                    drive_url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    handed_off_at TEXT,
                    completed_at TEXT,
                    failure_reason TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON trello_validation_cards(status)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS comment_resolutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    comment_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    original_text TEXT,
                    revised_text TEXT,
                    claude_reasoning TEXT,
                    resolved_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def insert(self, doc_id, card_id, blog_title, drive_url):
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trello_validation_cards
                    (doc_id, card_id, blog_title, drive_url, status, created_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (doc_id, card_id, blog_title, drive_url, now),
            )
            conn.commit()
        logger.info("Inserted trello_state row doc_id=%r card_id=%r", doc_id, card_id)

    def get_pending(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trello_validation_cards WHERE status = 'pending'"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_doc_id(self, doc_id):
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trello_validation_cards WHERE doc_id = ?",
                (doc_id,),
            ).fetchone()
        return dict(row) if row else None

    def mark_handed_off(self, doc_id):
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                "UPDATE trello_validation_cards SET status='handed_off', handed_off_at=? WHERE doc_id=?",
                (now, doc_id),
            )
            conn.commit()
        logger.info("Marked doc_id=%r as handed_off", doc_id)

    def mark_completed(self, doc_id):
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                "UPDATE trello_validation_cards SET status='completed', completed_at=? WHERE doc_id=?",
                (now, doc_id),
            )
            conn.commit()
        logger.info("Marked doc_id=%r as completed", doc_id)

    def mark_failed(self, doc_id, reason=""):
        with self._connect() as conn:
            conn.execute(
                "UPDATE trello_validation_cards SET status='failed', failure_reason=? WHERE doc_id=?",
                (reason, doc_id),
            )
            conn.commit()
        logger.info("Marked doc_id=%r as failed: %s", doc_id, reason)

    def reset_to_pending(self, doc_id):
        with self._connect() as conn:
            conn.execute(
                """UPDATE trello_validation_cards
                   SET status='pending', handed_off_at=NULL, completed_at=NULL, failure_reason=NULL
                   WHERE doc_id=?""",
                (doc_id,),
            )
            conn.commit()
        logger.info("Reset doc_id=%r to pending", doc_id)

    def log_comment_resolution(
        self,
        doc_id: str,
        comment_id: str,
        category: str,
        original_text: str,
        revised_text: str,
        claude_reasoning: str,
    ) -> None:
        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO comment_resolutions
                    (doc_id, comment_id, category, original_text, revised_text, claude_reasoning, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (doc_id, comment_id, category, original_text, revised_text, claude_reasoning, now),
            )
            conn.commit()
        logger.info(
            "Logged comment resolution doc_id=%r comment_id=%r category=%r",
            doc_id, comment_id, category,
        )

    def update_card_id(self, doc_id, card_id):
        with self._connect() as conn:
            conn.execute(
                "UPDATE trello_validation_cards SET card_id=? WHERE doc_id=?",
                (card_id, doc_id),
            )
            conn.commit()
        logger.info("Updated card_id for doc_id=%r to %r", doc_id, card_id)

    def get_all(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trello_validation_cards ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

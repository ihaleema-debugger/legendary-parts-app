"""SQLite state manager for the outreach pipeline."""

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).parent / "outreach_state.db"

# ── single source of truth for constrained column values ─────────────────────

ENUMS = {
    "status": frozenset({
        "intake", "triaged", "routed", "enriched",
        "drafted", "approved", "sent", "closed",
    }),
    "source": frozenset({
        "competitor-sheet", "alert",
    }),
    "decision": frozenset({
        "outreach", "review", "skip",
    }),
    "reason_code": frozenset({
        "SUPPLIER", "UGC-FORUM", "GEN-NEWS", "REL-EDITORIAL", "REL-DIRECTORY",
        "MARKETPLACE", "JUNK-PROFILE", "STAT-MIRROR", "IRRELEVANT-GEO", "UNKNOWN",
    }),
    "priority": frozenset({
        "high", "medium", "low",
    }),
    "mode": frozenset({
        "application", "pitch", "self-claim", "none",
    }),
    "draft_status": frozenset({
        "needs-review", "approved", "edited", "rejected",
    }),
    # What WE did (sends), tracked by outreach/poller.py. Distinct from
    # reply_status below, which is what THEY did — send_status never encodes
    # recipient behaviour (see poller.py's SEND_STATUS_* constants). NULL
    # ("not started") is always permitted regardless of this frozenset —
    # _validate_enum_fields() skips validation for None.
    "send_status": frozenset({
        "in-cadence", "exhausted", "withdrawn",
    }),
    "reply_status": frozenset({
        "none", "replied", "bounced", "unsub",
    }),
}

# decision required by each reason_code — enforced only in set_triage,
# never in upsert_prospect (which may receive a partial update with just one).
_REQUIRED_DECISION = {
    "SUPPLIER":       "outreach",
    "UGC-FORUM":      "outreach",
    "GEN-NEWS":       "outreach",
    "REL-EDITORIAL":  "outreach",
    "REL-DIRECTORY":  "outreach",
    "MARKETPLACE":    "skip",
    "JUNK-PROFILE":   "skip",
    "STAT-MIRROR":    "skip",
    "IRRELEVANT-GEO": "skip",
    "UNKNOWN":        "review",
}

# ── helpers ───────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_enum_fields(fields: dict) -> None:
    """Raise ValueError if any field with a known enum has a bad non-None value."""
    for col, val in fields.items():
        if col in ENUMS and val is not None:
            if val not in ENUMS[col]:
                raise ValueError(
                    f"invalid value {val!r} for field {col!r}; "
                    f"must be one of {sorted(ENUMS[col])}"
                )


# ── state class ───────────────────────────────────────────────────────────────

class OutreachState:
    """Tracks prospect rows in a local SQLite database."""

    def __init__(self, db_path=None):
        self._db_path = str(db_path or _DEFAULT_DB_PATH)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prospects (
                    id                    INTEGER PRIMARY KEY AUTOINCREMENT,

                    -- State spine
                    status                TEXT NOT NULL DEFAULT 'intake',

                    -- Intake (s0)
                    -- DESIGN: domain is UNIQUE by design — one domain lives in exactly one lane
                    -- (the contacts sheet is built single-lane upstream in Cowork). Do NOT change
                    -- to UNIQUE(domain, lane) without a NULL-safe migration: lane is nullable and
                    -- NULL != NULL in SQLite, which would silently break intake idempotency.
                    domain                TEXT NOT NULL UNIQUE,
                    authority_score       INTEGER,
                    email_on_file         TEXT,
                    source                TEXT,

                    -- Triage (s1)
                    decision              TEXT,
                    priority              TEXT,
                    reason_code           TEXT,
                    angle                 TEXT,
                    triage_hint           TEXT,
                    homepage_snapshot     TEXT,
                    fetch_attempts        INTEGER NOT NULL DEFAULT 0,

                    -- Routing (s2)
                    lane                  INTEGER,
                    mode                  TEXT,

                    -- Enrichment (s3)
                    contact_name          TEXT,
                    contact_email         TEXT,
                    personalisation_facts TEXT,
                    artefact_drive_link   TEXT,

                    -- Draft (s4)
                    subject               TEXT,
                    body                  TEXT,
                    language              TEXT,
                    draft_status          TEXT,

                    -- Send (s6)
                    gmail_draft_id        TEXT,
                    gmail_thread_id       TEXT,
                    send_status           TEXT,
                    cadence_step          INTEGER DEFAULT 0,
                    last_action_date      TEXT,

                    -- Outcome (s7)
                    reply_status          TEXT DEFAULT 'none',
                    placement             TEXT,
                    outcome_note          TEXT,

                    -- Metadata
                    created_at            TEXT NOT NULL,
                    updated_at            TEXT NOT NULL
                )
            """)
            try:
                conn.execute("ALTER TABLE prospects ADD COLUMN organisation TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists on existing databases

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_status       ON prospects(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision     ON prospects(decision)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_reason_code  ON prospects(reason_code)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_draft_status ON prospects(draft_status)"
            )
            conn.commit()

    # ── write ─────────────────────────────────────────────────────────────────

    def upsert_prospect(self, domain: str, **fields) -> None:
        """Insert or update a prospect row.

        On insert: status defaults to 'intake'; created_at is set to now.
        On conflict: only the keys present in fields are updated; id and
        created_at are never touched; untouched columns keep their values.

        Raises ValueError for any enum field whose value is invalid and non-None.
        Python None means "leave unset" — it is always accepted and skips validation.
        The literal string 'none' is a valid enum value (e.g. mode, reply_status).
        """
        _validate_enum_fields(fields)

        now = _utcnow()

        insert_cols = ["domain", "created_at", "updated_at"]
        insert_vals = [domain, now, now]

        # status defaults to 'intake' on first insert when not supplied
        if "status" not in fields:
            insert_cols.append("status")
            insert_vals.append("intake")

        for col, val in fields.items():
            insert_cols.append(col)
            insert_vals.append(val)

        # ON CONFLICT: update everything in fields + updated_at;
        # never touch domain or created_at.
        update_set = ["updated_at = excluded.updated_at"]
        for col in fields:
            update_set.append(f"{col} = excluded.{col}")

        cols_sql = ", ".join(insert_cols)
        ph_sql   = ", ".join(["?"] * len(insert_vals))
        upd_sql  = ", ".join(update_set)

        # ON CONFLICT(domain) merges by design — same domain re-entering updates its one row.
        # Safe ONLY while domain is single-lane (see schema note above). If a domain ever
        # arrives under a second lane, this silently overwrites the existing row (incl.
        # gmail_draft_id) — that scenario is assumed not to occur upstream.
        sql = (
            f"INSERT INTO prospects ({cols_sql}) VALUES ({ph_sql})"
            f" ON CONFLICT(domain) DO UPDATE SET {upd_sql}"
        )

        with self._connect() as conn:
            conn.execute(sql, insert_vals)
            conn.commit()
        logger.debug("upsert_prospect domain=%r", domain)

    def set_triage(
        self,
        domain: str,
        decision: str,
        priority: str,
        reason_code: str,
        angle: str,
        triage_hint: str = None,
        homepage_snapshot: str = None,
    ) -> None:
        """Write triage classification for an existing prospect.

        Raises ValueError on any validation failure — never silently accepts
        invalid data.
        """
        if not self.get_by_domain(domain):
            raise ValueError(f"domain not in DB: {domain!r}")

        if decision not in ENUMS["decision"]:
            raise ValueError(
                f"invalid decision {decision!r}; must be one of {sorted(ENUMS['decision'])}"
            )
        if priority not in ENUMS["priority"]:
            raise ValueError(
                f"invalid priority {priority!r}; must be one of {sorted(ENUMS['priority'])}"
            )
        if reason_code not in ENUMS["reason_code"]:
            raise ValueError(
                f"invalid reason_code {reason_code!r}; "
                f"must be one of {sorted(ENUMS['reason_code'])}"
            )

        required = _REQUIRED_DECISION[reason_code]
        if decision != required:
            raise ValueError(
                f"reason_code={reason_code!r} requires decision={required!r}, got {decision!r}"
            )

        now = _utcnow()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE prospects
                SET decision=?, priority=?, reason_code=?, angle=?,
                    triage_hint=?, homepage_snapshot=?,
                    status='triaged', updated_at=?
                WHERE domain=?
                """,
                (decision, priority, reason_code, angle,
                 triage_hint, homepage_snapshot, now, domain),
            )
            conn.commit()
        logger.info(
            "set_triage domain=%r decision=%r reason_code=%r", domain, decision, reason_code
        )

    # ── read ──────────────────────────────────────────────────────────────────

    def get_by_domain(self, domain: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM prospects WHERE domain = ?", (domain,)
            ).fetchone()
        return dict(row) if row else None

    def get_pending_triage(self) -> List[dict]:
        """Prospects written by intake but not yet triaged."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prospects WHERE status = 'intake' ORDER BY authority_score DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_pending_route(self) -> List[dict]:
        """Prospects triaged but not yet routed."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prospects WHERE status = 'triaged' ORDER BY created_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_human_queue(self) -> List[dict]:
        """Prospects that need a human triage decision."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM prospects WHERE decision = 'review' ORDER BY authority_score DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all(self, status: str = None, decision: str = None) -> List[dict]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if decision:
            clauses.append("decision = ?")
            params.append(decision)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM prospects {where} ORDER BY created_at DESC", params
            ).fetchall()
        return [dict(r) for r in rows]

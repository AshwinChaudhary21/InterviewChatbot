from typing import Optional, Dict, Any, List
from datetime import datetime
import os
import traceback

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor, Json
except ImportError:
    psycopg2 = None  # graceful fallback


DEFAULT_DB_NAME = "interview"

# ---------------------------------------------------------------------------
# Schema (auto-created on first connect)
# ---------------------------------------------------------------------------
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS candidates (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL DEFAULT '',
    email       TEXT NOT NULL UNIQUE,
    phone       TEXT NOT NULL DEFAULT '',
    position    TEXT NOT NULL DEFAULT '',
    tech_stack  JSONB NOT NULL DEFAULT '[]',
    meta        JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS answers (
    id           SERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    question_id  TEXT,
    question     TEXT NOT NULL DEFAULT '',
    answer       TEXT NOT NULL DEFAULT '',
    tech         TEXT NOT NULL DEFAULT 'General',
    score        REAL,
    timestamp    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


class PostgresDB:
    def __init__(self, dsn: Optional[str] = None):
        if psycopg2 is None:
            raise ImportError("psycopg2 is not installed. Run: pip install psycopg2-binary")

        self._dsn = dsn or os.getenv("POSTGRES_DSN") or os.getenv("DATABASE_URL")
        if not self._dsn:
            raise ValueError("POSTGRES_DSN or DATABASE_URL is not set.")

        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection helper
    # ------------------------------------------------------------------
    def _get_conn(self):
        return psycopg2.connect(self._dsn, sslmode="require")

    def _ensure_schema(self) -> None:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA_SQL)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Candidate operations
    # ------------------------------------------------------------------
    def upsert_candidate(self, email: str, profile: Dict[str, Any]) -> int:
        sql = """
            INSERT INTO candidates (name, email, phone, position, tech_stack, meta, updated_at)
            VALUES (%(name)s, %(email)s, %(phone)s, %(position)s, %(tech_stack)s, %(meta)s, NOW())
            ON CONFLICT (email) DO UPDATE SET
                name       = EXCLUDED.name,
                phone      = EXCLUDED.phone,
                position   = EXCLUDED.position,
                tech_stack = EXCLUDED.tech_stack,
                meta       = EXCLUDED.meta,
                updated_at = NOW()
            RETURNING id;
        """
        params = {
            "name":       profile.get("name", ""),
            "email":      email,
            "phone":      profile.get("phone", ""),
            "position":   profile.get("position", ""),
            "tech_stack": Json(profile.get("tech_stack", [])),
            "meta":       Json(profile.get("meta", {})),
        }

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            conn.commit()
            return row[0]
        finally:
            conn.close()

    def add_answer(self, candidate_id: int, answer: Dict[str, Any]) -> None:
        sql = """
            INSERT INTO answers (candidate_id, question_id, question, answer, tech, score, timestamp)
            VALUES (%(candidate_id)s, %(question_id)s, %(question)s, %(answer)s, %(tech)s, %(score)s, %(timestamp)s);
        """
        params = {
            "candidate_id": candidate_id,
            "question_id":  answer.get("question_id"),
            "question":     answer.get("question", ""),
            "answer":       answer.get("answer", ""),
            "tech":         answer.get("tech", "General"),
            "score":        answer.get("score"),
            "timestamp":    answer.get("timestamp", datetime.utcnow()),
        }

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def get_candidate_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        sql = "SELECT * FROM candidates WHERE email = %s;"
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (email,))
                row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_candidate_with_answers(self, email: str) -> Optional[Dict[str, Any]]:
        cand = self.get_candidate_by_email(email)
        if not cand:
            return None

        sql = "SELECT * FROM answers WHERE candidate_id = %s ORDER BY timestamp;"
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (cand["id"],))
                answers = [dict(r) for r in cur.fetchall()]
            cand["answers"] = answers
            return cand
        finally:
            conn.close()

    def list_candidates(self, limit: int = 50) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM candidates ORDER BY created_at DESC LIMIT %s;"
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (limit,))
                return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------
_db_instance: Optional[PostgresDB] = None


def get_db(dsn: Optional[str] = None) -> PostgresDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = PostgresDB(dsn=dsn)
    return _db_instance


# ---------------------------------------------------------------------------
# Module-level wrapper
# ---------------------------------------------------------------------------
_db_wrapper: Optional[PostgresDB] = None


def init_postgres(dsn: Optional[str] = None) -> None:
    global _db_wrapper
    if _db_wrapper is not None:
        return
    try:
        _db_wrapper = get_db(dsn)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize PostgreSQL: {e}")


def _normalize_answer_input(ans: Dict[str, Any]) -> Dict[str, Any]:
    a = dict(ans or {})
    a.setdefault("question_id", a.get("question_id") or a.get("qid") or None)
    a.setdefault("question",    a.get("question") or a.get("q") or "")
    a.setdefault("answer",      a.get("answer") or a.get("response") or "")
    a.setdefault("tech",        a.get("tech") or "General")
    a.setdefault("score",       a.get("score", None))
    a.setdefault("timestamp",   a.get("timestamp") or datetime.utcnow())
    return a


def save_candidate_and_answers(
    candidate: Dict[str, Any],
    answers_list: List[Dict[str, Any]],
) -> str:
    global _db_wrapper

    if _db_wrapper is None:
        try:
            init_postgres()
        except Exception as e:
            raise ConnectionError(f"PostgreSQL not initialized and auto-init failed: {e}")

    if not isinstance(candidate, dict):
        raise ValueError("candidate must be a dict")

    email = (
        candidate.get("email")
        or candidate.get("Email")
        or candidate.get("email_address")
        or ""
    ).strip()

    if not email:
        raise ValueError("Candidate must include an 'email' field.")

    profile = {
        "name":       candidate.get("full_name", candidate.get("name", "")).strip(),
        "email":      email,
        "phone":      candidate.get("phone", candidate.get("phone_number", "")).strip(),
        "position":   str(candidate.get("position", candidate.get("desired_positions", ""))),
        "meta":       candidate.get("meta", {"status": "in_progress"}),
        "tech_stack": candidate.get("tech_stack", []),
    }

    try:
        candidate_id = _db_wrapper.upsert_candidate(email=email, profile=profile)

        for raw in answers_list or []:
            norm = _normalize_answer_input(raw)
            ans_doc = {
                "question_id": norm.get("question_id"),
                "question":    norm.get("question"),
                "answer":      norm.get("answer"),
                "tech":        norm.get("tech"),
                "score":       norm.get("score"),
                "timestamp":   norm.get("timestamp"),
            }
            _db_wrapper.add_answer(candidate_id, ans_doc)

        return str(candidate_id)

    except Exception as ex:
        tb = traceback.format_exc()
        raise RuntimeError(f"Failed to save candidate and answers: {ex}\n\n{tb}")
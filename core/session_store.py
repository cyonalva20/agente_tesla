import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _database_uri() -> str | None:
    return os.getenv("DATABASE_URI") or os.getenv("DATABASE_URL")


def normalize_database_uri(uri: str) -> str:
    parsed = urlparse(uri)
    if parsed.hostname in {"localhost", "127.0.0.1"}:
        return uri
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    return urlunparse(parsed._replace(query=urlencode(query)))


def coerce_message_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


class SessionStore(Protocol):
    def setup(self) -> None: ...
    def get_or_create_session(self, phone: str) -> dict: ...
    def get_session(self, phone: str) -> dict | None: ...
    def list_conversations(self) -> list[dict]: ...
    def get_messages(self, phone: str) -> list[dict]: ...
    def append_message(self, phone: str, role: str, text: Any) -> None: ...
    def set_agent_enabled(self, phone: str, enabled: bool) -> dict: ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}

    def setup(self) -> None:
        return None

    def get_or_create_session(self, phone: str) -> dict:
        if phone not in self.sessions:
            self.sessions[phone] = {
                "phone": phone,
                "session_id": str(uuid.uuid4()),
                "agent_enabled": True,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "messages": [],
            }
        return self.sessions[phone]

    def get_session(self, phone: str) -> dict | None:
        return self.sessions.get(phone)

    def list_conversations(self) -> list[dict]:
        conversations = []
        for phone, info in self.sessions.items():
            messages = info.get("messages", [])
            conversations.append({
                "phone": phone,
                "last_message": messages[-1]["text"] if messages else "Sin mensajes",
                "agent_enabled": info["agent_enabled"],
                "last_updated": info["last_updated"],
            })
        conversations.sort(key=lambda item: item["last_updated"], reverse=True)
        return conversations

    def get_messages(self, phone: str) -> list[dict]:
        session = self.sessions.get(phone)
        return list(session.get("messages", [])) if session else []

    def append_message(self, phone: str, role: str, text: Any) -> None:
        session = self.get_or_create_session(phone)
        session["messages"].append({"role": role, "text": coerce_message_text(text)})
        session["last_updated"] = datetime.now(timezone.utc).isoformat()

    def set_agent_enabled(self, phone: str, enabled: bool) -> dict:
        session = self.get_or_create_session(phone)
        session["agent_enabled"] = enabled
        session["last_updated"] = datetime.now(timezone.utc).isoformat()
        return session


class PostgresSessionStore:
    def __init__(self, database_uri: str) -> None:
        self.database_uri = normalize_database_uri(database_uri)

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            self.database_uri,
            autocommit=True,
            row_factory=dict_row,
        )

    def setup(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crm_sessions (
                    phone TEXT PRIMARY KEY,
                    session_id UUID NOT NULL,
                    agent_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    telefono TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS crm_messages (
                    id BIGSERIAL PRIMARY KEY,
                    phone TEXT NOT NULL REFERENCES crm_sessions(phone) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'bot', 'human')),
                    text TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_crm_messages_phone_id
                ON crm_messages(phone, id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_crm_sessions_last_updated
                ON crm_sessions(last_updated DESC)
            """)

    def get_or_create_session(self, phone: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO crm_sessions (phone, session_id, telefono)
                VALUES (%s, %s, %s)
                ON CONFLICT (phone) DO UPDATE
                SET telefono = EXCLUDED.telefono
                RETURNING phone, session_id::text, agent_enabled, telefono, last_updated
                """,
                (phone, str(uuid.uuid4()), phone),
            ).fetchone()
        return dict(row)

    def get_session(self, phone: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT phone, session_id::text, agent_enabled, telefono, last_updated
                FROM crm_sessions
                WHERE phone = %s
                """,
                (phone,),
            ).fetchone()
        return dict(row) if row else None

    def list_conversations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT
                    s.phone,
                    COALESCE(m.text, 'Sin mensajes') AS last_message,
                    s.agent_enabled,
                    s.last_updated
                FROM crm_sessions s
                LEFT JOIN LATERAL (
                    SELECT text
                    FROM crm_messages
                    WHERE phone = s.phone
                    ORDER BY id DESC
                    LIMIT 1
                ) m ON true
                ORDER BY s.last_updated DESC
            """).fetchall()
        return [dict(row) for row in rows]

    def get_messages(self, phone: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, text
                FROM crm_messages
                WHERE phone = %s
                ORDER BY id ASC
                """,
                (phone,),
            ).fetchall()
        return [dict(row) for row in rows]

    def append_message(self, phone: str, role: str, text: Any) -> None:
        text_value = coerce_message_text(text)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO crm_sessions (phone, session_id, telefono)
                VALUES (%s, %s, %s)
                ON CONFLICT (phone) DO NOTHING
                """,
                (phone, str(uuid.uuid4()), phone),
            )
            conn.execute(
                "INSERT INTO crm_messages (phone, role, text) VALUES (%s, %s, %s)",
                (phone, role, text_value),
            )
            conn.execute(
                "UPDATE crm_sessions SET last_updated = now() WHERE phone = %s",
                (phone,),
            )

    def set_agent_enabled(self, phone: str, enabled: bool) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO crm_sessions (phone, session_id, telefono, agent_enabled)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (phone) DO UPDATE
                SET agent_enabled = EXCLUDED.agent_enabled,
                    last_updated = now()
                RETURNING phone, session_id::text, agent_enabled, telefono, last_updated
                """,
                (phone, str(uuid.uuid4()), phone, enabled),
            ).fetchone()
        return dict(row)


def create_session_store() -> SessionStore:
    uri = _database_uri()
    if uri:
        return PostgresSessionStore(uri)
    return InMemorySessionStore()

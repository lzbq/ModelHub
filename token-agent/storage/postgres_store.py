"""postgres_store.py 定义了一个可选的 PostgreSQL 消息存储类：PostgresMessageStore。
它的作用是：当项目配置了 DATABASE_URL 时，把聊天会话和消息持久化保存到 Postgres；
如果没配置或连接失败，就自动禁用，不影响主程序继续运行。"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PostgresMessageStore:
    """Persist chat messages to Postgres when DATABASE_URL is configured."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.enabled = bool(database_url)
        self._psycopg = None
        if not self.enabled:
            return
        try:
            import psycopg
            self._psycopg = psycopg
            self._init_schema()
            logger.info("Postgres 消息落库已启用")
        except Exception as ex:
            self.enabled = False
            logger.warning(f"Postgres 不可用，消息落库已关闭: {ex}")

    def _connect(self):
        return self._psycopg.connect(self.database_url)  # type: ignore[union-attr]

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conv_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id UUID PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    conv_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_user_conv_created
                ON messages(user_id, conv_id, created_at)
            """)
            conn.commit()

    async def add_message(
        self,
        user_id: str,
        conv_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.enabled:
            return
        await asyncio.to_thread(self._add_message_sync, user_id, conv_id, role, content, metadata or {})

    def _add_message_sync(
        self,
        user_id: str,
        conv_id: str,
        role: str,
        content: str,
        metadata: Dict[str, Any],
    ) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO conversations(conv_id, user_id, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (conv_id)
                    DO UPDATE SET updated_at = now(), user_id = EXCLUDED.user_id
                    """,
                    (conv_id, user_id),
                )
                conn.execute(
                    """
                    INSERT INTO messages(id, user_id, conv_id, role, content, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        uuid.uuid4(),
                        user_id,
                        conv_id,
                        role,
                        content,
                        json.dumps(metadata, ensure_ascii=False),
                        datetime.now(),
                    ),
                )
                conn.commit()
        except Exception as ex:
            logger.warning(f"写入 Postgres 消息失败: {ex}")

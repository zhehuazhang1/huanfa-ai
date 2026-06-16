from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class MySqlStore:
    """Minimal MySQL store matching the AppStore row/rows/transaction interface."""

    def __init__(self, database_url: str, init_schema: bool = False) -> None:
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyMySQL is required for mysql DATABASE_URL") from exc

        self._pymysql = pymysql
        self._dict_cursor = DictCursor
        self.conn = pymysql.connect(
            **self._parse_database_url(database_url),
            cursorclass=DictCursor,
            autocommit=False,
            charset="utf8mb4",
        )
        if init_schema:
            self.init_schema()

    @staticmethod
    def _parse_database_url(database_url: str) -> dict:
        from urllib.parse import urlparse

        parsed = urlparse(database_url)
        if parsed.scheme not in {"mysql", "mysql+pymysql"}:
            raise ValueError("DATABASE_URL must start with mysql:// or mysql+pymysql://")
        return {
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 3306,
            "user": parsed.username or "",
            "password": parsed.password or "",
            "database": parsed.path.lstrip("/"),
        }

    @staticmethod
    def _convert_placeholders(sql: str) -> str:
        return sql.replace("?", "%s")

    @contextmanager
    def transaction(self) -> Iterator:
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def init_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema_mysql.sql"
        statements = [part.strip() for part in schema_path.read_text(encoding="utf-8").split(";") if part.strip()]
        with self.conn.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        self.conn.commit()

    def row(self, sql: str, params: tuple = ()) -> dict | None:
        with self.conn.cursor() as cursor:
            cursor.execute(self._convert_placeholders(sql), params)
            return cursor.fetchone()

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self.conn.cursor() as cursor:
            cursor.execute(self._convert_placeholders(sql), params)
            return list(cursor.fetchall())

    def seed_demo(self) -> None:
        # Production MySQL should be seeded by migrations/admin tools, not app startup.
        return None

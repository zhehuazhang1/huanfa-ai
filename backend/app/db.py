from __future__ import annotations

import os
from urllib.parse import urlparse

from .mysql_store import MySqlStore
from .store import AppStore


def build_store_from_env() -> AppStore | MySqlStore:
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        parsed = urlparse(database_url)
        if parsed.scheme in {"mysql", "mysql+pymysql"}:
            return MySqlStore(
                database_url,
                init_schema=os.getenv("MYSQL_INIT_SCHEMA", "0") == "1",
            )
        if parsed.scheme == "sqlite":
            path = parsed.path or ":memory:"
            if path in {"/:memory:", ":memory:"}:
                path = ":memory:"
            return AppStore(path)

    db_path = os.getenv("HAIR_AI_DB_PATH", "hair_ai_dev.sqlite3")
    return AppStore(db_path)

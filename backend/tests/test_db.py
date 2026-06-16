import os
import unittest
from unittest.mock import patch

from app.db import build_store_from_env
from app.mysql_store import MySqlStore
from app.store import AppStore


class DatabaseFactoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("DATABASE_URL", None)
        os.environ.pop("HAIR_AI_DB_PATH", None)

    def test_default_store_is_sqlite(self) -> None:
        os.environ["HAIR_AI_DB_PATH"] = ":memory:"
        store = build_store_from_env()
        self.assertIsInstance(store, AppStore)

    def test_sqlite_database_url_uses_sqlite_store(self) -> None:
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"
        store = build_store_from_env()
        self.assertIsInstance(store, AppStore)

    def test_mysql_url_wires_mysql_store(self) -> None:
        os.environ["DATABASE_URL"] = "mysql+pymysql://user:pass@db:3306/hair_ai"
        with patch("app.db.MySqlStore") as store_class:
            build_store_from_env()
        store_class.assert_called_once_with(
            "mysql+pymysql://user:pass@db:3306/hair_ai",
            init_schema=False,
        )

    def test_mysql_placeholder_conversion(self) -> None:
        sql = "SELECT * FROM orders WHERE tenant_id = ? AND store_id = ?"
        self.assertEqual(
            MySqlStore._convert_placeholders(sql),
            "SELECT * FROM orders WHERE tenant_id = %s AND store_id = %s",
        )

    def test_mysql_url_parse(self) -> None:
        parsed = MySqlStore._parse_database_url("mysql+pymysql://user:pass@db:3307/hair_ai")
        self.assertEqual(parsed["host"], "db")
        self.assertEqual(parsed["port"], 3307)
        self.assertEqual(parsed["user"], "user")
        self.assertEqual(parsed["password"], "pass")
        self.assertEqual(parsed["database"], "hair_ai")


if __name__ == "__main__":
    unittest.main()

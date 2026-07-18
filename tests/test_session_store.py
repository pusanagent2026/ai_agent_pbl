from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from github_ai_agent import session_store


class SessionStoreTests(unittest.TestCase):
    def test_all_oauth_connections_survive_a_new_proxy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.db"
            with patch.dict(
                os.environ,
                {"SESSION_DB_PATH": str(database), "SESSION_ENC_KEY": ""},
                clear=False,
            ):
                session_store._fernet.cache_clear()
                session = session_store.get_or_create("browser-session")
                session["github_access_token"] = "github-token"
                session["google_access_token"] = "google-token"
                session["google_refresh_token"] = "google-refresh"
                session["notion_access_token"] = "notion-token"
                session["notion_refresh_token"] = "notion-refresh"
                session["notion_workspace_name"] = "Workspace"
                session["notion_database_id"] = "database-id"
                session["notion_page_id"] = "page-id"

                restored = session_store.get_or_create("browser-session")
                self.assertEqual(restored["github_access_token"], "github-token")
                self.assertEqual(restored["google_access_token"], "google-token")
                self.assertEqual(restored["google_refresh_token"], "google-refresh")
                self.assertEqual(restored["notion_access_token"], "notion-token")
                self.assertEqual(restored["notion_refresh_token"], "notion-refresh")
                self.assertEqual(restored["notion_workspace_name"], "Workspace")
                self.assertEqual(restored["notion_database_id"], "database-id")
                self.assertEqual(restored["notion_page_id"], "page-id")
                self.assertTrue(database.with_suffix(".key").exists())
                session_store._fernet.cache_clear()

    def test_logout_clear_removes_all_connections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sessions.db"
            with patch.dict(
                os.environ,
                {"SESSION_DB_PATH": str(database), "SESSION_ENC_KEY": ""},
                clear=False,
            ):
                session_store._fernet.cache_clear()
                session = session_store.get_or_create("browser-session")
                session["github_access_token"] = "github-token"
                session["google_access_token"] = "google-token"
                session["notion_access_token"] = "notion-token"

                session_store.clear("browser-session")
                restored = session_store.get_or_create("browser-session")
                self.assertNotIn("github_access_token", restored)
                self.assertNotIn("google_access_token", restored)
                self.assertNotIn("notion_access_token", restored)
                session_store._fernet.cache_clear()


if __name__ == "__main__":
    unittest.main()

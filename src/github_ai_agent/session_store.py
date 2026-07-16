from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

_SCHEMA_PATH = Path(__file__).resolve().parent / "session_store_schema.sql"

# dict key -> (table, column, encrypted?)
_FIELD_MAP: dict[str, tuple[str, str, bool]] = {
    "github_access_token": ("github_credentials", "access_token_enc", True),
    "github_login": ("github_credentials", "login", False),
    "installation_id": ("github_credentials", "installation_id", False),
    "google_access_token": ("google_credentials", "access_token_enc", True),
    "google_refresh_token": ("google_credentials", "refresh_token_enc", True),
    "google_email": ("google_credentials", "email", False),
}
_ENC_KEY_VERSION = 1


def _db_path() -> str:
    return os.environ.get("SESSION_DB_PATH", "sessions.db")


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("SESSION_ENC_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "SESSION_ENC_KEY is required to store session credentials. "
            "Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode("ascii"))


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(_db_path())
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        with connection:
            yield connection
    finally:
        connection.close()


def _encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode("utf-8"))


def _decrypt(value: bytes | None) -> str:
    if not value:
        return ""
    return _fernet().decrypt(bytes(value)).decode("utf-8")


class SessionProxy(MutableMapping[str, str]):
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id

    def __getitem__(self, key: str) -> str:
        table, column, encrypted = _FIELD_MAP[key]
        with _connection() as connection:
            row = connection.execute(
                f"SELECT {column} FROM {table} WHERE session_id = ?",
                (self.session_id,),
            ).fetchone()
        if row is None or row[0] is None:
            raise KeyError(key)
        return _decrypt(row[0]) if encrypted else str(row[0])

    def __setitem__(self, key: str, value: str) -> None:
        table, column, encrypted = _FIELD_MAP[key]
        if encrypted:
            columns_sql = f"{column}, enc_key_version"
            placeholders_sql = "?, ?"
            update_sql = f"{column} = excluded.{column}, enc_key_version = excluded.enc_key_version"
            params = (self.session_id, _encrypt(str(value)), _ENC_KEY_VERSION)
        else:
            columns_sql = column
            placeholders_sql = "?"
            update_sql = f"{column} = excluded.{column}"
            params = (self.session_id, str(value))
        with _connection() as connection:
            connection.execute(
                f"""
                INSERT INTO {table} (session_id, {columns_sql}, updated_at)
                VALUES (?, {placeholders_sql}, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(session_id) DO UPDATE SET
                    {update_sql},
                    updated_at = excluded.updated_at
                """,
                params,
            )

    def __delitem__(self, key: str) -> None:
        table, column, _ = _FIELD_MAP[key]
        with _connection() as connection:
            connection.execute(
                f"UPDATE {table} SET {column} = NULL WHERE session_id = ?",
                (self.session_id,),
            )

    def __iter__(self) -> Iterator[str]:
        for key in _FIELD_MAP:
            if key in self:
                yield key

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def __contains__(self, key: object) -> bool:
        if key not in _FIELD_MAP:
            return False
        try:
            self[key]  # type: ignore[index]
        except KeyError:
            return False
        return True


def get_or_create(session_id: str) -> SessionProxy:
    with _connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO sessions (session_id) VALUES (?)",
            (session_id,),
        )
        connection.execute(
            """
            UPDATE sessions SET last_seen_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE session_id = ?
            """,
            (session_id,),
        )
    return SessionProxy(session_id)


def clear(session_id: str) -> None:
    with _connection() as connection:
        connection.execute("DELETE FROM github_credentials WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM google_credentials WHERE session_id = ?", (session_id,))

-- Session persistence for github_ai_agent.web
-- Replaces the in-memory SESSIONS dict (web.py) so state survives process restarts.
--
-- Per-connection pragmas a future store layer must set on every new
-- sqlite3.connect() (these are NOT persisted in the file, unlike journal_mode):
--   PRAGMA foreign_keys = ON;
--
-- OAuth CSRF state (web.py's OAUTH_STATES dict) is intentionally NOT modeled
-- here. It only needs to live between "redirect to provider" and "provider's
-- callback" (seconds), so losing it on a server restart just means the user
-- clicks the connect button again -- unlike losing a stored token, which
-- forces a full re-consent. Kept in-memory on purpose.

-- WAL lets readers and the writer avoid blocking each other; ThreadingHTTPServer
-- hands each request its own thread, so concurrent access is the common case.
-- Persisted in the db file itself, so this only needs to run once.
PRAGMA journal_mode = WAL;

-- Bump this and add a migration when a released schema needs a breaking
-- change. Still 1 because this schema hasn't shipped/been read by any store
-- layer yet.
PRAGMA user_version = 1;

-- One row per browser session (keyed by the github_ai_agent_session cookie).
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    expires_at   TEXT
);

-- GitHub side: user OAuth token (github_access_token/github_login) and the
-- separate GitHub App installation flow (installation_id) can each land
-- independently, so every column but session_id is nullable.
--
-- refresh_token_enc/access_token_expires_at exist because GitHub Apps can be
-- configured to expire user tokens (8h default). _exchange_github_code()
-- currently only reads access_token and drops refresh_token/expires_in from
-- GitHub's response -- these columns stay unused until that's fixed too.
CREATE TABLE IF NOT EXISTS github_credentials (
    session_id               TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    login                    TEXT,
    installation_id          TEXT,
    access_token_enc         BLOB,
    refresh_token_enc        BLOB,
    access_token_expires_at  TEXT,
    enc_key_version          INTEGER,
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Google side: access_token + optional refresh_token (Google only returns
-- refresh_token on first consent with prompt=consent) + expiry so a store
-- layer can decide when to refresh.
CREATE TABLE IF NOT EXISTS google_credentials (
    session_id               TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    email                    TEXT,
    access_token_enc         BLOB,
    refresh_token_enc        BLOB,
    access_token_expires_at  TEXT,
    enc_key_version          INTEGER,
    updated_at               TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Notion is currently a single shared integration secret from .env
-- (NotionToolClient reads NOTION_API_KEY, not a per-session token), so this
-- table is unused today. Reserved for if/when Notion moves to per-user OAuth.
CREATE TABLE IF NOT EXISTS notion_credentials (
    session_id        TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    workspace_id       TEXT,
    workspace_name     TEXT,
    database_id        TEXT,
    page_id            TEXT,
    access_token_enc   BLOB,
    refresh_token_enc  BLOB,
    enc_key_version    INTEGER,
    updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

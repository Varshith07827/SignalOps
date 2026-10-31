-- Voice-of-Store app database: accounts, sessions, the case workflow and the in-app inbox.
-- The feedback itself stays in the pack's CSV files; this only stores what people do in the app.
-- Every statement is safe to run again (db/seed.py and the server both apply it on start).

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'store')),
    store_id      TEXT,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    -- Store managers belong to exactly one store; head office belongs to none.
    CHECK ((role = 'store') = (store_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,              -- SHA-256 of the cookie value; the value itself is never stored
    user_id    INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- A case is one problem at one store. Store reports start here; cases found in the feedback get a row the
-- first time someone acts on them (until then they are simply open).
CREATE TABLE IF NOT EXISTS cases (
    id            INTEGER PRIMARY KEY,
    ref           TEXT NOT NULL UNIQUE,       -- 'R-00001' for store reports, the incident id for feedback cases
    source        TEXT NOT NULL CHECK (source IN ('store_report', 'feedback')),
    store_id      TEXT,
    issue_type_id TEXT NOT NULL,
    severity      TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    team          TEXT NOT NULL,
    summary       TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'awaiting_confirmation', 'closed', 'reopened')),
    reported_by   INTEGER REFERENCES users (id),
    created_at    TEXT NOT NULL,
    due_at        TEXT,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_by_store ON cases (store_id, status);

CREATE TABLE IF NOT EXISTS case_events (
    id      INTEGER PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    at      TEXT NOT NULL,
    user_id INTEGER REFERENCES users (id),
    kind    TEXT NOT NULL CHECK (kind IN ('reported', 'started', 'note', 'resolved', 'confirmed', 'not_fixed')),
    note    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_by_case ON case_events (case_id, at);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    recipient   TEXT NOT NULL,                -- 'admin' or a store id
    case_id     INTEGER NOT NULL REFERENCES cases (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('new_report', 'confirm_request', 'confirmed', 'not_fixed')),
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    read_at     TEXT,
    answered_at TEXT                          -- set when a store answers a confirm_request
);
CREATE INDEX IF NOT EXISTS messages_by_recipient ON messages (recipient, read_at);

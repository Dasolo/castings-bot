-- Sources: telegram channels, websites, etc.
CREATE TABLE sources (
    id          SERIAL PRIMARY KEY,
    source_type TEXT    NOT NULL,               -- 'telegram', 'website_somesite'
    external_id TEXT    NOT NULL,               -- tg_channel_id or url
    title       TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT true,
    verified    BOOLEAN NOT NULL DEFAULT false, -- only verified sources are processed
    added_by    BIGINT,                         -- tg_user_id of who added (null = manual)
    added_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_type, external_id)
);

-- Raw messages written by listeners
CREATE TABLE raw_messages (
    id              SERIAL PRIMARY KEY,
    source_id       INTEGER     NOT NULL REFERENCES sources (id),
    source_type     TEXT        NOT NULL, -- denormalized for fast parser filtering
    external_msg_id TEXT        NOT NULL,
    raw_text        TEXT,
    raw_data        JSONB,                -- media, metadata, source-specific fields
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    parsed_at       TIMESTAMPTZ,         -- NULL = not yet processed by parser
    UNIQUE (source_id, external_msg_id)
);

CREATE INDEX idx_raw_messages_unparsed
    ON raw_messages (source_type, received_at)
    WHERE parsed_at IS NULL;

-- Parsed castings written by parsers
CREATE TABLE castings (
    id             SERIAL PRIMARY KEY,
    raw_message_id INTEGER NOT NULL REFERENCES raw_messages (id),
    text_hash      TEXT UNIQUE,    -- dedup: same casting reposted to multiple channels
    gender         TEXT,           -- 'male', 'female', 'any'
    age_min        SMALLINT,
    age_max        SMALLINT,
    location       TEXT,
    project_type   TEXT,           -- 'film', 'theatre', 'ad', 'series'
    fee_type       TEXT,           -- 'paid', 'free', 'unknown'
    deadline       DATE,
    media_file_ids TEXT[],
    classified_by  TEXT,           -- 'regex', 'llm'
    confidence     SMALLINT,       -- 0-100
    is_valid       BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Users
CREATE TABLE users (
    id         SERIAL PRIMARY KEY,
    tg_user_id BIGINT UNIQUE NOT NULL,
    username   TEXT,
    is_active  BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-user filters
CREATE TABLE user_filters (
    id                SERIAL PRIMARY KEY,
    user_id           INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    gender            TEXT,
    age               SMALLINT,
    location          TEXT,
    project_types     TEXT[],
    fee_only          BOOLEAN NOT NULL DEFAULT false,
    notify_immediately BOOLEAN NOT NULL DEFAULT true
);

-- Sent log: prevents duplicate delivery
CREATE TABLE sent_log (
    user_id    INTEGER     NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    casting_id INTEGER     NOT NULL REFERENCES castings (id) ON DELETE CASCADE,
    sent_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, casting_id)
);

-- 001_init.sql
-- Full schema. Run on empty DB to bring it to current state.

CREATE TABLE sources (
    id          SERIAL PRIMARY KEY,
    source_type TEXT    NOT NULL,
    external_id TEXT    NOT NULL,
    title       TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    verified    BOOLEAN NOT NULL DEFAULT FALSE,
    added_by    BIGINT,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_type, external_id)
);

CREATE TABLE raw_messages (
    id              SERIAL PRIMARY KEY,
    source_id       INTEGER     NOT NULL REFERENCES sources (id),
    source_type     TEXT        NOT NULL,
    external_msg_id TEXT        NOT NULL,
    raw_text        TEXT,
    raw_data        JSONB,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    parsed_at       TIMESTAMPTZ,
    UNIQUE (source_id, external_msg_id)
);

CREATE INDEX idx_raw_messages_unparsed
    ON raw_messages (source_type, received_at)
    WHERE parsed_at IS NULL;

CREATE TABLE castings (
    id              SERIAL PRIMARY KEY,
    raw_message_id  INTEGER     NOT NULL REFERENCES raw_messages (id),
    text_hash       TEXT        UNIQUE,
    location        TEXT,
    project_type    TEXT,       -- 'film', 'theatre', 'ad', 'series'
    deadline        DATE,
    media_file_ids  TEXT[],
    classified_by   TEXT,       -- 'regex', 'llm'
    confidence      SMALLINT,   -- 0-100
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE vacancies (
    id          SERIAL PRIMARY KEY,
    casting_id  INTEGER     NOT NULL REFERENCES castings (id) ON DELETE CASCADE,
    gender      TEXT,           -- 'male', 'female', 'any'
    age_min     SMALLINT,
    age_max     SMALLINT,
    fee_max     INTEGER,        -- max fee in RUB
    fee_type    TEXT,           -- 'paid', 'free', 'unknown'
    is_valid    BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_vacancies_casting_id ON vacancies (casting_id);

CREATE TABLE users (
    id          SERIAL PRIMARY KEY,
    tg_user_id  BIGINT  NOT NULL UNIQUE,
    username    TEXT,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE user_filters (
    id                  SERIAL PRIMARY KEY,
    user_id             INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    gender              TEXT,
    age                 SMALLINT,
    location            TEXT,
    project_types       TEXT[],
    fee_only            BOOLEAN NOT NULL DEFAULT FALSE,
    notify_immediately  BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE sent_log (
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    casting_id  INTEGER NOT NULL REFERENCES castings (id) ON DELETE CASCADE,
    sent_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, casting_id)
);
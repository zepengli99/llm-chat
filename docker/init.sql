CREATE TABLE IF NOT EXISTS users (
    id          UUID         NOT NULL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);

CREATE TABLE IF NOT EXISTS conversations (
    id         UUID         NOT NULL PRIMARY KEY,
    user_id    UUID         NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(255),
    created_at TIMESTAMPTZ  NOT NULL,
    updated_at TIMESTAMPTZ  NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id                  UUID        NOT NULL PRIMARY KEY,
    conversation_id     UUID        NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role                VARCHAR(20) NOT NULL,
    content             TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id);

-- Stamp alembic so `alembic upgrade head` on app startup is a no-op
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);
INSERT INTO alembic_version (version_num) VALUES ('001') ON CONFLICT DO NOTHING;

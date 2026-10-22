
-- Migration 011: Durable inbound message queue.
-- Keep Inbox separate from conversations and outbox.

CREATE TABLE inbox (
    id                  BIGSERIAL PRIMARY KEY,
    channel             TEXT NOT NULL
                        CHECK (channel IN ('whatsapp', 'telegram')),
    user_id             TEXT NOT NULL,
    chat_id             TEXT NOT NULL,
    message_id          TEXT NOT NULL,
    body                TEXT NOT NULL,
    is_start            BOOLEAN NOT NULL DEFAULT FALSE,
    start_payload       TEXT,

    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'processing', 'processed', 'dead')),
    attempts            INT NOT NULL DEFAULT 0
                        CHECK (attempts >= 0),
    next_attempt_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_until        TIMESTAMPTZ,
    last_error          TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at        TIMESTAMPTZ,

    CONSTRAINT uq_inbox_channel_chat_message
        UNIQUE (channel, chat_id, message_id)
);

CREATE INDEX idx_inbox_due
    ON inbox (next_attempt_at, id)
    WHERE status IN ('pending', 'processing');

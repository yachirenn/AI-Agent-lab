ALTER TABLE customers ADD COLUMN personalization_enabled BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE customer_preferences (
    id                  BIGSERIAL PRIMARY KEY,
    customer_id         UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    pref_key            TEXT NOT NULL,
    pref_value          TEXT NOT NULL,
    confidence          NUMERIC(3,2) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source              TEXT NOT NULL DEFAULT 'chat' CHECK (source IN ('chat')),
    evidence_message_id BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (customer_id, pref_key)
);
CREATE TABLE IF NOT EXISTS knowledge_base (
    id            BIGSERIAL PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'faq' CHECK (category IN ('faq', 'pricing', 'station', 'troubleshooting', 'points', 'general')),
    content       TEXT NOT NULL,
    embedding     DOUBLE PRECISION[],
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge_base (category);
CREATE INDEX IF NOT EXISTS idx_kb_fts ON knowledge_base USING gin (to_tsvector('indonesian', title || ' ' || content));

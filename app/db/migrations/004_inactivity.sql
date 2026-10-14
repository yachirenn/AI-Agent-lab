CREATE TABLE consent_events (
  id          BIGSERIAL PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customers(id),
  granted     BOOLEAN NOT NULL,
  source      TEXT NOT NULL,                 -- 'registration' | 'command'
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_consent_customer ON consent_events (customer_id, created_at DESC);

-- Backfill: customer yang sudah setuju sebelum tabel ini ada
INSERT INTO consent_events (customer_id, granted, source, created_at)
SELECT id, TRUE, 'registration', consent_at FROM customers
WHERE consent_marketing AND consent_at IS NOT NULL;

CREATE TABLE inactivity_alerts (
  id                BIGSERIAL PRIMARY KEY,
  customer_id       UUID NOT NULL REFERENCES customers(id),
  last_visit_at     TIMESTAMPTZ NOT NULL,
  median_gap_hours  NUMERIC(8,1) NOT NULL,
  status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
  retention_sent_at TIMESTAMPTZ,
  detected_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at       TIMESTAMPTZ
);
-- Satu alert terbuka per customer: job yang jalan dua kali tidak menggandakan alert
CREATE UNIQUE INDEX uq_inactivity_open ON inactivity_alerts (customer_id) WHERE status = 'open';
CREATE INDEX idx_inactivity_retention ON inactivity_alerts (customer_id, retention_sent_at);
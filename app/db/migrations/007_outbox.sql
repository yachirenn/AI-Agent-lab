CREATE TABLE outbox (
  id              BIGSERIAL PRIMARY KEY,
  kind            TEXT NOT NULL CHECK (kind IN ('notification', 'staff_alert')),
  channel         TEXT NOT NULL,
  recipient       TEXT NOT NULL,
  customer_id     UUID REFERENCES customers(id),
  ticket_id       BIGINT REFERENCES cs_tickets(id),
  body            TEXT NOT NULL,
  dedup_key       TEXT UNIQUE,                  -- NULL boleh banyak; non-NULL unik
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sending', 'sent', 'dead')),
  attempts        INT NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  locked_until    TIMESTAMPTZ,
  last_error      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at         TIMESTAMPTZ
);
CREATE INDEX idx_outbox_due ON outbox (next_attempt_at) WHERE status IN ('pending', 'sending');
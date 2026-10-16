CREATE TABLE reply_drafts (
  id          BIGSERIAL PRIMARY KEY,
  ticket_id   BIGINT NOT NULL REFERENCES cs_tickets(id),
  body        TEXT NOT NULL CHECK (char_length(body) BETWEEN 5 AND 500),
  drafted_by  TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  decided_by  TEXT,
  decided_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_drafts_pending ON reply_drafts (id) WHERE status = 'pending';

CREATE TABLE ticket_events (
  id         BIGSERIAL PRIMARY KEY,
  ticket_id  BIGINT NOT NULL REFERENCES cs_tickets(id),
  actor      TEXT NOT NULL,
  action     TEXT NOT NULL CHECK (action IN ('draft_reply', 'approved_reply', 'rejected_reply')),
  detail     TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
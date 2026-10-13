CREATE TABLE cs_tickets (
  id          BIGSERIAL PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customers(id),
  level       SMALLINT NOT NULL CHECK (level IN (2, 3)),
  category    TEXT NOT NULL,
  summary     TEXT NOT NULL,
  source      TEXT NOT NULL CHECK (source IN ('rule', 'agent')),
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved')),
  notified_at TIMESTAMPTZ,            -- terisi jika alert staf berhasil terkirim
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

-- Satu tiket aktif per (customer, kategori): laporan berulang tidak membuat alert berulang.
CREATE UNIQUE INDEX uq_cs_open_ticket ON cs_tickets (customer_id, category) WHERE status <> 'resolved';
CREATE INDEX idx_cs_queue ON cs_tickets (status, level DESC, created_at);
-- Dijalankan otomatis HANYA saat volume Postgres pertama kali dibuat.
-- Untuk mengulang dari nol: docker compose down -v && docker compose up -d

CREATE SEQUENCE customer_code_seq START 1;

CREATE TABLE stations (
  id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  area TEXT
);

CREATE TABLE customers (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_code         TEXT UNIQUE NOT NULL
                        DEFAULT ('ENV-' || lpad(nextval('customer_code_seq')::text, 6, '0')),
  name                  TEXT,
  driver_type           TEXT CHECK (driver_type IN ('ride_hailing', 'private', 'fleet')),
  home_area             TEXT,
  main_route            TEXT,
  consent_marketing     BOOLEAN NOT NULL DEFAULT FALSE,
  consent_at            TIMESTAMPTZ,
  registered_station_id UUID REFERENCES stations(id),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (NOT consent_marketing OR consent_at IS NOT NULL)
);

-- Satu customer bisa punya banyak channel (WhatsApp, Telegram, ...)
CREATE TABLE customer_identities (
  id          BIGSERIAL PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  channel     TEXT NOT NULL CHECK (channel IN ('whatsapp', 'telegram', 'sim')),
  external_id TEXT NOT NULL,
  UNIQUE (channel, external_id)
);

CREATE TABLE vehicles (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  model       TEXT NOT NULL,
  plate_no    TEXT
);

CREATE TABLE charging_sessions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id TEXT UNIQUE NOT NULL,   -- idempotency key dari CMS
  customer_id UUID REFERENCES customers(id),
  station_id  UUID NOT NULL REFERENCES stations(id),
  charger_id  TEXT NOT NULL,
  kwh         NUMERIC(10,2) NOT NULL CHECK (kwh > 0),
  amount_idr  BIGINT NOT NULL CHECK (amount_idr >= 0),
  started_at  TIMESTAMPTZ NOT NULL,
  ended_at    TIMESTAMPTZ NOT NULL,
  CHECK (ended_at >= started_at)
);
CREATE INDEX idx_sessions_customer ON charging_sessions (customer_id, started_at DESC);
CREATE INDEX idx_sessions_station  ON charging_sessions (station_id, started_at DESC);

-- Ledger append-only: saldo = SUM(delta), tidak pernah di-UPDATE
CREATE TABLE points_ledger (
  id          BIGSERIAL PRIMARY KEY,
  customer_id UUID NOT NULL REFERENCES customers(id),
  delta       INTEGER NOT NULL CHECK (delta <> 0),
  reason      TEXT NOT NULL,
  ref_id      TEXT NOT NULL,          -- id sesi charging / id tiket CS
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (customer_id, reason, ref_id) -- poin untuk satu sumber tidak bisa dobel
);

CREATE TABLE conversations (
  id                 BIGSERIAL PRIMARY KEY,
  customer_id        UUID NOT NULL REFERENCES customers(id),
  channel            TEXT NOT NULL,
  channel_message_id TEXT,            -- id pesan dari platform (untuk dedup retry)
  direction          TEXT NOT NULL CHECK (direction IN ('in', 'out')),
  body               TEXT NOT NULL,
  escalation_level   SMALLINT NOT NULL DEFAULT 1 CHECK (escalation_level BETWEEN 1 AND 3),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_conv_channel_msg
  ON conversations (channel, channel_message_id)
  WHERE channel_message_id IS NOT NULL;
CREATE INDEX idx_conv_customer ON conversations (customer_id, created_at DESC);
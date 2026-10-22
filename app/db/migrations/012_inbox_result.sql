-- Migration 012: Persist the result of inbound message processing.
-- result_ready distinguishes an unprocessed result from a valid no-reply result.

ALTER TABLE inbox
    ADD COLUMN customer_id UUID REFERENCES customers(id),
    ADD COLUMN reply_body TEXT,
    ADD COLUMN result_ready BOOLEAN NOT NULL DEFAULT FALSE;

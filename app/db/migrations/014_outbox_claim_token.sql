-- Migration 014: Add a fencing token for each Outbox claim.
ALTER TABLE outbox
    ADD COLUMN claim_token UUID;

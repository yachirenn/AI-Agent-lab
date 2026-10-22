-- Migration 013: Add a fencing token for each Inbox claim.
ALTER TABLE inbox
    ADD COLUMN claim_token UUID;

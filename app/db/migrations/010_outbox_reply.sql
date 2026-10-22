-- Migration 010: Allow customer replies in the outbox.
-- Keep the existing notification and staff_alert kinds.

ALTER TABLE outbox
    DROP CONSTRAINT outbox_kind_check;

ALTER TABLE outbox
    ADD CONSTRAINT outbox_kind_check
    CHECK (kind IN ('notification', 'staff_alert', 'reply'));

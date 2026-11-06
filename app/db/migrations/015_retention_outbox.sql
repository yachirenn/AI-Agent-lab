-- Migration 015: Kirim pesan retensi inaktivitas lewat Outbox.
--
-- Sebelumnya `inactivity.send_retention` mengirim pesan langsung ke Telegram/WhatsApp
-- lalu menandai `retention_sent_at`. Jika proses mati di antaranya, pesan bisa hilang
-- (sudah ditandai terkirim) atau terkirim dua kali. Pesan lain sudah memakai Outbox,
-- jadi retensi disamakan.
--
-- Perubahan:
--   1) jenis outbox baru: 'retention'
--   2) kolom retention_alert_id untuk menautkan baris Outbox ke alert inaktivitas
--   3) dedup_key deterministik -> alert yang sama tidak pernah diantre dua kali
--   4) `retention_sent_at` HANYA diisi setelah pengiriman berhasil (delivery ack)

ALTER TABLE outbox
    DROP CONSTRAINT outbox_kind_check;

ALTER TABLE outbox
    ADD CONSTRAINT outbox_kind_check
    CHECK (kind IN ('notification', 'staff_alert', 'reply', 'retention'));

ALTER TABLE outbox
    ADD COLUMN retention_alert_id BIGINT REFERENCES inactivity_alerts(id);

-- Satu alert hanya boleh punya satu baris Outbox retensi.
CREATE UNIQUE INDEX uq_outbox_retention_alert
    ON outbox (retention_alert_id)
    WHERE retention_alert_id IS NOT NULL;

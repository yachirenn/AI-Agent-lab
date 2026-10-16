-- Migration 008: Multi-station EV charging network
-- Menambahkan stasiun pengisian Enerva di titik-titik strategis (Sanur, Ubud, Canggu, Airport)

INSERT INTO stations (code, name, area)
VALUES
  ('sanur-hub', 'Enerva Sanur Port Hub', 'Sanur'),
  ('ubud-central', 'Enerva Ubud Monkey Forest', 'Ubud'),
  ('canggu-coastal', 'Enerva Canggu Shortcut', 'Canggu'),
  ('airport-hub', 'Enerva Ngurah Rai Hub', 'Tuban')
ON CONFLICT (code) DO NOTHING;

ALTER TABLE customers
  ADD COLUMN registration_state TEXT NOT NULL DEFAULT 'ask_name'
  CHECK (registration_state IN
    ('ask_name','ask_vehicle','ask_driver_type','ask_area','ask_route','ask_consent','done'));

INSERT INTO stations (code, name, area)
VALUES ('sunset-road', 'Enerva Sunset Road', 'Kuta')
ON CONFLICT (code) DO NOTHING;
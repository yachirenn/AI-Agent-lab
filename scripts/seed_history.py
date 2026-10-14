"""Pemakaian: python -m scripts.seed_history ENV-000003 --last-visit-days-ago 10
Hapus     : python -m scripts.seed_history ENV-000003 --clean"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

from app.db import repo

parser = argparse.ArgumentParser()
parser.add_argument("customer_code")
parser.add_argument("--last-visit-days-ago", type=int, default=10)
parser.add_argument("--clean", action="store_true")
args = parser.parse_args()

customer = repo.get_customer_by_code(args.customer_code)
if customer is None:
    sys.exit("customer tidak ditemukan")
prefix = f"seed-{args.customer_code}-"

with repo.tx() as conn:
    if args.clean:
        n = conn.execute("DELETE FROM charging_sessions WHERE external_id LIKE %s", (prefix + "%",)).rowcount
        conn.execute("DELETE FROM inactivity_alerts WHERE customer_id = %s", (customer["id"],))
        sys.exit(f"{n} sesi seed dan semua alert customer ini dihapus")

    station = conn.execute("SELECT id FROM stations WHERE code = 'sunset-road'").fetchone()["id"]
    last = datetime.now(timezone.utc) - timedelta(days=args.last_visit_days_ago)
    created = 0
    for d in range(21):                      # 3 minggu mundur dari kunjungan terakhir
        if d % 7 in (3, 6):                  # libur 2 hari/minggu: ±5x per minggu
            continue
        start = last - timedelta(days=d, hours=1)
        created += conn.execute(
            """
            INSERT INTO charging_sessions
              (external_id, customer_id, station_id, charger_id, kwh, amount_idr, started_at, ended_at)
            VALUES (%s, %s, %s, '01', 30, 70000, %s, %s)
            ON CONFLICT (external_id) DO NOTHING
            """,
            (f"{prefix}{args.last_visit_days_ago}-{d}", customer["id"], station, start, start + timedelta(minutes=35)),
        ).rowcount
    newer = conn.execute(
        "SELECT max(started_at) AS m FROM charging_sessions WHERE customer_id = %s AND external_id NOT LIKE 'seed-%%'",
        (customer["id"],),
    ).fetchone()["m"]

print(f"{created} sesi dibuat (tanpa poin).")
if newer and newer > last:
    print("PERINGATAN: customer ini punya sesi asli yang lebih baru, jadi tidak akan dianggap inaktif.")
    print("Geser sesi aslinya (hanya untuk data dev):")
    print("  UPDATE charging_sessions SET started_at = started_at - interval '12 days',")
    print("    ended_at = ended_at - interval '12 days'")
    print(f"  WHERE customer_id = (SELECT id FROM customers WHERE customer_code = '{args.customer_code}')")
    print("    AND external_id NOT LIKE 'seed-%';")
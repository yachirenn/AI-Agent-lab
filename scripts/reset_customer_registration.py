"""Script untuk me-reset alur registrasi nomor WhatsApp atau customer_code pengujian.

Pemakaian:
  Preview : python -m scripts.reset_customer_registration 085959533825
  Eksekusi: python -m scripts.reset_customer_registration 085959533825 --confirm
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from app.db import repo


def _clean_phone(raw: str) -> str:
    cleaned = raw.strip().replace(" ", "").replace("-", "")
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if cleaned.startswith("08"):
        cleaned = "628" + cleaned[2:]
    return cleaned


def find_customer(identifier: str) -> tuple[dict[str, Any], str] | None:
    id_clean = identifier.strip()
    if id_clean.upper().startswith("ENV-"):
        c = repo.get_customer_by_code(id_clean.upper())
        if c:
            return c, "code"
        return None

    phone = _clean_phone(id_clean)
    with repo.tx() as conn:
        row = conn.execute(
            """
            SELECT c.* FROM customers c
            JOIN customer_identities i ON i.customer_id = c.id
            WHERE i.channel = 'whatsapp' AND i.external_id = %s
            """,
            (phone,),
        ).fetchone()
        if row:
            return row, f"whatsapp:{phone}"
    return None


def reset_customer(customer_id: Any) -> None:
    with repo.tx() as conn:
        # 1. Reset state pendaftaran pada tabel customers
        conn.execute(
            """
            UPDATE customers
            SET registration_state = 'ask_name',
                name = NULL,
                driver_type = NULL,
                home_area = NULL,
                main_route = NULL,
                consent_marketing = FALSE,
                consent_at = NULL,
                registered_station_id = NULL
            WHERE id = %s
            """,
            (customer_id,),
        )

        # 2. Hapus data relasi pengujian agar sesi registrasi benar-benar baru
        conn.execute("DELETE FROM vehicles WHERE customer_id = %s", (customer_id,))
        conn.execute("DELETE FROM customer_preferences WHERE customer_id = %s", (customer_id,))
        conn.execute("DELETE FROM consent_events WHERE customer_id = %s", (customer_id,))
        conn.execute("DELETE FROM conversations WHERE customer_id = %s", (customer_id,))
        conn.execute("DELETE FROM cs_tickets WHERE customer_id = %s", (customer_id,))
        conn.execute("DELETE FROM inactivity_alerts WHERE customer_id = %s", (customer_id,))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset state registrasi customer untuk testing")
    parser.add_argument("identifier", help="Nomor HP WhatsApp (misal: 085959533825) atau Customer ID (ENV-000001)")
    parser.add_argument("--confirm", action="store_true", help="Eksekusi reset langsung ke database")
    args = parser.parse_args()

    found = find_customer(args.identifier)
    if not found:
        print(f"❌ Customer dengan identitas '{args.identifier}' tidak ditemukan di database.")
        return 1

    cust, found_via = found
    cid = cust["id"]
    code = cust["customer_code"]
    name = cust.get("name") or "-"
    state = cust["registration_state"]

    print("\n=== DATA CUSTOMER DITEMUKAN ===")
    print(f"Customer ID   : {code}")
    print(f"Ditemukan via : {found_via}")
    print(f"Nama Saat Ini : {name}")
    print(f"State Regist  : {state}")
    print("================================")

    if not args.confirm:
        print("\n⚠️  MODE PREVIEW (Database belum diubah).")
        print("Aksi ini akan me-reset:")
        print("  - registration_state -> 'ask_name'")
        print("  - Mengosongkan nama, tipe driver, domisili, rute, dan kendaraan")
        print("  - Menghapus riwayat percakapan pendaftaran testing sebelumnya")
        print(f"\nUntuk mengeksekusi, jalankan kembali dengan flag --confirm:\n")
        print(f"  python -m scripts.reset_customer_registration {args.identifier} --confirm\n")
        return 0

    print("\nMengeksekusi reset state...")
    reset_customer(cid)
    print("✅ Berhasil! State registrasi customer telah di-reset ke 'ask_name'.")
    print(f"Sekarang nomor {args.identifier} bisa kirim 'MULAI sunset-road' di WhatsApp untuk mulai dari awal.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

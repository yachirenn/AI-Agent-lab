"""Pemakaian: python -m scripts.cms_feeder ENV-000003"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()
BASE = os.environ.get("API_BASE", "http://localhost:8000")
SECRET = os.environ["CMS_WEBHOOK_SECRET"]
code = sys.argv[1] if len(sys.argv) > 1 else None


def event(**override):
    end = datetime.now(timezone.utc)
    base = {
        "external_id": f"cms-{uuid.uuid4()}",
        "station_code": "sunset-road",
        "charger_id": "04",
        "customer_code": code,
        "kwh": "450",
        "amount_idr": 195000,
        "started_at": (end - timedelta(minutes=38)).isoformat(),
        "ended_at": end.isoformat(),
    }
    return {**base, **override}


def post(label, payload, secret=SECRET):
    r = httpx.post(f"{BASE}/webhook/cms", json=payload, headers={"X-CMS-Secret": secret}, timeout=10)
    print(f"{label:<30} -> {r.status_code} {r.text[:100]}")


valid = event()
post("1. transaksi valid", valid)
post("2. KIRIM ULANG (duplikat)", valid)
post("3. stasiun tidak dikenal", event(station_code="tidak-ada"))
post("4. kWh negatif", event(kwh="-5"))
post("5. selesai < mulai", event(started_at="2026-10-13T10:00:00+07:00", ended_at="2026-10-13T09:00:00+07:00"))
post("6. tanpa timezone", event(started_at="2026-10-13T10:00:00", ended_at="2026-10-13T11:00:00"))
post("7. secret salah", event(), secret="salah")
post("8. customer tidak dikenal", event(customer_code="ENV-999999"))
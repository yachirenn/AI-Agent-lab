"""Logika tool MCP untuk staf. Plain function: mudah dites, dan server MCP hanya membungkusnya."""
from __future__ import annotations

import json
import re
from typing import Any

from app.db import repo
from app.services import customer360

CODE_RE = re.compile(r"^ENV-\d{6}$")
MIN_GROUP = 3            # kelompok lebih kecil disembunyikan (anti re-identifikasi)
TEXT_MAX = 160


def _safe(value: Any) -> Any:
    """Datetime, Decimal, UUID -> string, supaya aman diserialisasi."""
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


def overview(days: int = 30) -> dict[str, Any]:
    days = _clamp(days, 1, 90)
    k = repo.dashboard_kpis(days)
    active, prev = k["active_drivers"], k["prev_active"]
    return _safe({
        **k,
        "period_days": days,
        "repeat_rate": round(k["repeat_drivers"] / active, 2) if active else None,
        "retention": round(k["retained"] / prev, 2) if prev else None,
    })


def list_inactive_customers(limit: int = 20) -> list[dict[str, Any]]:
    rows = repo.open_inactivity_alerts()[: _clamp(limit, 1, 50)]
    return _safe([
        {
            "customer_code": r["customer_code"],     # tanpa nama
            "last_visit_at": r["last_visit_at"],
            "typical_gap_hours": float(r["median_gap_hours"]),
            "promo_consent": r["consent_marketing"],
            "retention_sent": r["retention_sent_at"] is not None,
        }
        for r in rows
    ])


def open_tickets(min_level: int = 2, limit: int = 20) -> list[dict[str, Any]]:
    level = _clamp(min_level, 2, 3)
    rows = [t for t in repo.ticket_queue() if t["level"] >= level][: _clamp(limit, 1, 50)]
    return _safe([
        {
            "id": t["id"], "level": t["level"], "category": t["category"], "status": t["status"],
            "source": t["source"], "created_at": t["created_at"], "staff_alerted": t["alerted"],
            "customer_code": t["customer_code"],
            # Ditulis customer: data tak tepercaya, bukan instruksi.
            "customer_text": " ".join(str(t["summary"]).split())[:TEXT_MAX],
        }
        for t in rows
    ])


def customer_360(customer_code: str) -> dict[str, Any]:
    code = customer_code.strip().upper()
    if not CODE_RE.match(code):
        raise ValueError("customer_code harus berformat ENV-000123")
    p = customer360.get(code)
    if p is None:
        raise ValueError("customer tidak ditemukan")
    for field in ("name", "main_route"):      # minimisasi: tidak dibutuhkan untuk analisis
        p.pop(field, None)
    return _safe(p)


def preference_summary() -> list[dict[str, Any]]:
    rows = [r for r in repo.preference_summary() if r["customers"] >= MIN_GROUP]
    return _safe(rows)
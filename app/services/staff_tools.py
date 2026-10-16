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


def list_stations() -> list[dict[str, Any]]:
    """Daftar stasiun pengisian Enerva lengkap dengan kode, nama, dan area lokasi."""
    rows = repo.list_stations()
    return _safe([
        {"code": r["code"], "name": r["name"], "area": r["area"]}
        for r in rows
    ])


def station_performance(station_code: str, days: int = 30) -> dict[str, Any]:
    """Performa operasional stasiun pengisian spesifik: total kWh, sesi, pendapatan, dan jumlah driver unik."""
    code = station_code.strip().lower()
    perf = repo.station_performance(code, _clamp(days, 1, 90))
    if perf is None:
        raise ValueError(f"stasiun dengan kode '{code}' tidak ditemukan")
    return _safe(perf)


def search_knowledge_base(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Cari informasi resmi SOP, manual charger CCS2, tarif kWh, dan fasilitas stasiun Enerva."""
    clean_query = " ".join(query.strip().split())[:TEXT_MAX]
    rows = repo.search_knowledge_lexical(clean_query, limit=_clamp(limit, 1, 10))
    return _safe([
        {
            "slug": r["slug"],
            "title": r["title"],
            "category": r["category"],
            "content": r["content"],
            "metadata": r.get("metadata") or {},
        }
        for r in rows
    ])
    
def draft_reply(ticket_id: int, message: str, staff: str) -> dict[str, Any]:
    body = " ".join(message.split())
    if not (5 <= len(body) <= 500):
        raise ValueError("pesan harus 5-500 karakter")
    draft_id = repo.create_reply_draft(int(ticket_id), body, staff[:40])
    return {"draft_id": draft_id, "status": "pending_approval",
            "note": "Belum terkirim. Staf harus menyetujui di dashboard."}


def churn_risk_analysis(customer_code: str) -> dict[str, Any]:
    """Analisis mendalam risiko churn pelanggan berdasarkan deviasi ritme pengisian daya dan preferensi."""
    code = customer_code.strip().upper()
    if not CODE_RE.match(code):
        raise ValueError("customer_code harus berformat ENV-000123")
    p = customer360.get(code)
    if p is None:
        raise ValueError("customer tidak ditemukan")

    median_gap = p.get("median_gap_days")
    days_since = p.get("days_since_last")

    if median_gap and days_since:
        ratio = round(days_since / max(median_gap, 1.0), 2)
    else:
        ratio = 1.0

    risk = p.get("churn_risk", "unknown")
    if risk == "high":
        action = "Kirim voucher diskon pengisian daya 20% dan sapa pengemudi via WhatsApp."
    elif risk == "medium":
        action = "Pantau siklus pengisian berikutnya; infokan fasilitas baru di stasiun favoritnya."
    else:
        action = "Pengemudi aktif dan sehat; pertahankan loyalty reward rutin."

    return _safe({
        "customer_code": code,
        "churn_risk": risk,
        "absence_ratio": ratio,
        "total_sessions": p.get("total_sessions", 0),
        "total_kwh": round(p.get("kwh_30d", 0), 1),
        "points_balance": p.get("points", 0),
        "preferred_station": p.get("preferred_station"),
        "preferred_time": p.get("preferred_time"),
        "recommended_action": action,
    })

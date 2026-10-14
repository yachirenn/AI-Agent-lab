from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.db import repo


def churn_risk(
    *, days_since_last: float | None, median_gap_days: float | None, sessions: int, has_open_alert: bool
) -> str:
    """Aturan sederhana (bukan ML): seberapa jauh absen sekarang dibanding ritme customer sendiri."""
    if has_open_alert:
        return "high"
    if sessions < 4 or days_since_last is None or median_gap_days is None:
        return "unknown"   # data belum cukup untuk menilai
    ratio = days_since_last / max(median_gap_days, 1.0)   # lantai 1 hari: jeda jam-jaman tidak berlebihan
    return "medium" if ratio >= 1.5 else "low"


def _window(hour: int | None) -> str | None:
    return None if hour is None else f"{hour:02d}:00-{(hour + 1) % 24:02d}:00"


def get(customer_code: str) -> dict[str, Any] | None:
    raw = repo.customer_360_raw(customer_code)
    if raw is None:
        return None

    last = raw["last_visit"]
    days_since = (datetime.now(timezone.utc) - last).total_seconds() / 86400 if last else None
    median_days = raw["median_gap_s"] / 86400 if raw["median_gap_s"] is not None else None

    if raw["has_open_alert"]:
        status = "inactive"
    elif last is None:
        status = "new"
    else:
        status = "active" if days_since <= 30 else "dormant"

    kwh_30d = raw["kwh_30d"]
    return {
        "customer_code": raw["customer_code"],
        "name": raw["name"],
        "vehicles": [v["model"] for v in repo.list_vehicles(raw["id"])],
        "driver_type": raw["driver_type"],
        "home_area": raw["home_area"],
        "main_route": raw["main_route"],
        "consent_marketing": raw["consent_marketing"],
        # Hanya konsumsi di Enerva. Total kebutuhan energi butuh data telematics (Phase 3).
        "kwh_per_day": kwh_30d / 30,
        "kwh_per_week": kwh_30d / 30 * 7,
        "kwh_30d": kwh_30d,
        "visits_per_week": raw["visits_28d"] / 4,
        "total_sessions": raw["total_sessions"],
        "preferred_time": _window(raw["preferred_hour"]),
        "preferred_station": raw["preferred_station"],
        "points": raw["points"],
        "last_visit": last,
        "days_since_last": days_since,
        "status": status,
        "churn_risk": churn_risk(
            days_since_last=days_since,
            median_gap_days=median_days,
            sessions=raw["total_sessions"],
            has_open_alert=raw["has_open_alert"],
        ),
    }
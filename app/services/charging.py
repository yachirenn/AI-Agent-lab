from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.channels import telegram
from app.db import repo
from app.schemas import ChargingEvent
from app.services import loyalty

logger = logging.getLogger(__name__)


def process_charging_event(event: ChargingEvent) -> dict[str, Any]:
    return repo.ingest_charging_session(
        external_id=event.external_id,
        station_code=event.station_code,
        charger_id=event.charger_id,
        customer_code=event.customer_code,
        kwh=event.kwh,
        amount_idr=event.amount_idr,
        started_at=event.started_at,
        ended_at=event.ended_at,
        points=loyalty.points_for_kwh(event.kwh),
    )


def _id(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def notify_customer(result: dict[str, Any], kwh: Decimal) -> None:
    """Dipanggil SETELAH commit. Gagal kirim hanya di-log; poin sudah aman di ledger."""
    try:
        chat_id = repo.get_identity(result["customer_id"], "telegram")
        if chat_id is None:
            return
        text = (
            f"Charging selesai: {kwh:.2f} kWh ⚡\n"
            f"Anda mendapat {_id(result['points_awarded'])} poin.\n"
            f"Saldo: {_id(result['balance'])} poin."
        )
        telegram.send_message(chat_id, text)
        repo.record_message(result["customer_id"], "telegram", "out", text)
    except Exception:
        logger.exception("notifikasi charging gagal customer=%s", result.get("customer_id"))
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from app.db import repo
from app.schemas import ChargingEvent
from app.services import loyalty


def _id(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _render(kwh: Decimal) -> Callable[[int, int], str]:
    def render(points: int, balance: int) -> str:
        return (
            f"Charging selesai: {kwh:.2f} kWh ⚡\n"
            f"Anda mendapat {_id(points)} poin.\n"
            f"Saldo: {_id(balance)} poin."
        )
    return render


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
        notify=_render(event.kwh),
    )
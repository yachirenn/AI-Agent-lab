from __future__ import annotations

from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ChargingEvent(BaseModel):
    """Kontrak data dari CMS. Apa pun yang tidak lolos di sini ditolak sebelum menyentuh DB."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=100)    # kunci idempotency dari CMS
    station_code: str = Field(min_length=1, max_length=64)
    charger_id: str = Field(min_length=1, max_length=32)
    customer_code: str | None = Field(default=None, max_length=32)
    kwh: Decimal = Field(gt=0, le=500, max_digits=10, decimal_places=2)
    amount_idr: int = Field(ge=0, le=100_000_000)
    started_at: AwareDatetime        # wajib punya timezone, supaya tidak ambigu
    ended_at: AwareDatetime

    @model_validator(mode="after")
    def _ended_after_started(self) -> "ChargingEvent":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at tidak boleh lebih awal dari started_at")
        return self
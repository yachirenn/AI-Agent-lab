from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ORDER = ("ask_name", "ask_vehicle", "ask_driver_type", "ask_area", "ask_route", "ask_consent", "done")

PROMPTS = {
    "ask_name": (
        "Halo, selamat datang di Enerva ⚡\n"
        "Data yang Anda isi dipakai untuk layanan charging, poin, dan notifikasi Enerva.\n\n"
        "Siapa nama Anda?"
    ),
    "ask_vehicle": "Kendaraan apa yang Anda pakai? (contoh: BYD M6)",
    "ask_driver_type": (
        "Apa tipe pengemudi Anda?\n"
        "1. Ride-hailing\n2. Pribadi\n3. Armada (fleet)\n"
        "Balas dengan angka 1-3."
    ),
    "ask_area": "Di area mana Anda tinggal? (contoh: Jimbaran)",
    "ask_route": "Rute utama Anda sehari-hari? (contoh: Jimbaran - Airport - Seminyak)",
    "ask_consent": "Terakhir: boleh kami mengirim info promo dan reward lewat chat ini? Balas YA atau TIDAK.",
}

_DRIVER_TYPES = {
    "1": "ride_hailing", "ride-hailing": "ride_hailing", "ride hailing": "ride_hailing",
    "2": "private", "pribadi": "private", "private": "private",
    "3": "fleet", "fleet": "fleet", "armada": "fleet",
}
_YES, _NO = {"ya", "y", "iya", "yes"}, {"tidak", "t", "tdk", "no", "n"}


class InvalidAnswer(ValueError):
    """Pesannya aman ditampilkan ke customer."""


@dataclass(frozen=True)
class Answer:
    fields: dict[str, Any] = field(default_factory=dict)
    vehicle_model: str | None = None


def _clean(raw: str, label: str, min_len: int = 2, max_len: int = 80) -> str:
    value = " ".join(raw.split())
    if value.startswith ("/") or value.startswith("@"):
        raise InvalidAnswer(f"{label} tidak valid.")
    if not (min_len <= len(value) <= max_len):
        raise InvalidAnswer(f"{label} harus {min_len}-{max_len} karakter.")
    return value


def handle_answer(state: str, raw: str) -> tuple[str, Answer]:
    """Validasi jawaban untuk `state`; kembalikan (state berikutnya, data yang disimpan)."""
    if state == "done" or state not in ORDER:
        raise ValueError(f"state tidak valid: {state}")
    next_state = ORDER[ORDER.index(state) + 1]

    if state == "ask_name":
        return next_state, Answer({"name": _clean(raw, "Nama")})
    if state == "ask_vehicle":
        return next_state, Answer(vehicle_model=_clean(raw, "Tipe kendaraan"))
    if state == "ask_driver_type":
        driver = _DRIVER_TYPES.get(" ".join(raw.lower().split()))
        if driver is None:
            raise InvalidAnswer("Pilihan tidak dikenali.")
        return next_state, Answer({"driver_type": driver})
    if state == "ask_area":
        return next_state, Answer({"home_area": _clean(raw, "Area")})
    if state == "ask_route":
        return next_state, Answer({"main_route": _clean(raw, "Rute", max_len=120)})

    answer = " ".join(raw.lower().split())   # ask_consent
    if answer in _YES:
        return next_state, Answer({"consent_marketing": True})
    if answer in _NO:
        return next_state, Answer({"consent_marketing": False})
    raise InvalidAnswer("Mohon balas YA atau TIDAK.")
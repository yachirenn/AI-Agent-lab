from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ORDER = ("ask_name", "ask_vehicle", "ask_driver_type", "ask_area", "ask_route", "ask_consent", "done")

PROMPTS = {
    "ask_name": (
        "Halo Kak, selamat datang di Enerva SPKLU! ⚡🚗\n"
        "Senang banget bisa menyapa Kakak. Supaya proses pengisian daya, poin reward, dan update promo Kakak tercatat rapi, kenalan dulu yuk.\n\n"
        "Siapa nama Anda? (Boleh sertakan nama panggilan akrab Kakak ya)"
    ),
    "ask_vehicle": (
        "Salam kenal ya, Kak! 🚗✨\n"
        "Kalau boleh tahu, kendaraan listrik apa yang sehari-hari Kakak kendarai? (Contoh: BYD M6, Ioniq 5, Wuling Binguo, dll.)"
    ),
    "ask_driver_type": (
        "Keren banget mobilnya! ⚡\n"
        "Kendaraan ini utamanya dipakai untuk keperluan apa nih Kak?\n\n"
        "1. Ride-hailing (Taksi online / Ojol)\n"
        "2. Pribadi (Harian / Keluarga)\n"
        "3. Armada (fleet / Bisnis)\n\n"
        "Cukup balas dengan angka 1, 2, atau 3 ya Kak."
    ),
    "ask_area": (
        "Sip, dicatat! 📍\n"
        "Domisili atau area tempat tinggal Kakak biasanya di daerah mana? (Contoh: Sanur, Kuta, Ubud, Jimbaran)"
    ),
    "ask_route": (
        "Biar kami bisa merekomendasikan stasiun pengisian yang paling pas, rute utama yang biasa Kakak lewati sehari-hari ke mana saja nih? 🛣️\n"
        "(Contoh: Jimbaran - Airport - Seminyak)"
    ),
    "ask_consent": (
        "Tinggal satu langkah lagi nih, Kak! 🎉\n\n"
        "Boleh ya kami kirimkan info promo tarif kWh, voucher diskon, dan reward poin lewat chat ini? 🎁\n"
        "Ketik YA jika setuju, atau TIDAK jika hanya butuh struk transaksi saja."
    ),
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

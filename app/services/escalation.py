from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.db import repo
from app.services import alerts


@dataclass(frozen=True)
class Escalation:
    level: int
    category: str


# Urutan penting: kategori pertama yang cocok menang, keselamatan di paling atas.
_RULES: list[tuple[int, str, re.Pattern[str]]] = [
    (3, "safety", re.compile(
        r"terbakar|kebakaran|berasap|ada asap|keluar asap|bau gosong|korslet|percikan|kesetrum|tersengat|meledak|ledakan")),
    (3, "stranded", re.compile(
        r"terjebak|terdampar|mogok|kehabisan baterai|baterai habis|tidak bisa pulang|butuh derek")),
    (3, "charger_failure", re.compile(
        r"charger (rusak|mati|error)|charging (berhenti|stop|gagal)|berhenti sendiri|tidak mau (nge)?charge|(gun|kabel) (macet|tidak bisa)")),
    (3, "payment", re.compile(
        r"terpotong|kepotong|dobel (bayar|charge|tagihan)|bayar dobel|double (charge|bayar)|sudah bayar tapi")),
    (3, "emergency", re.compile(r"\bdarurat\b|\bemergency\b|\bsos\b")),
    (2, "points_issue", re.compile(r"poin (saya )?(tidak masuk|belum masuk|kurang|salah|hilang)|selisih poin")),
    (2, "refund", re.compile(r"refund|kembalikan uang|uang kembali|pengembalian dana")),
    (2, "complaint", re.compile(r"komplain|complain|kecewa|mengecewakan|tidak puas|pelayanan buruk")),
]


def classify(text: str) -> Escalation | None:
    """None = level 1 (normal), diserahkan ke agent."""
    normalized = " ".join(text.lower().split())
    for level, category, pattern in _RULES:
        if pattern.search(normalized):
            return Escalation(level, category)
    return None


def process(customer: dict[str, Any], esc: Escalation, text: str) -> str:
    summary = " ".join(text.split())[:300]
    ticket, created = repo.create_ticket(customer["id"], esc.level, esc.category, summary, "rule")
    if created and esc.level == 3:
        alerts.notify_staff(ticket["id"], customer, esc.category, summary)
    return _reply(esc, ticket["id"], created)


def _reply(esc: Escalation, ticket_id: int, created: bool) -> str:
    if esc.level == 3:
        text = (
            f"Laporan darurat Anda sudah diteruskan ke tim Enerva (tiket #{ticket_id})."
            if created
            else f"Laporan darurat Anda sebelumnya sudah kami terima (tiket #{ticket_id}) dan sedang ditindaklanjuti."
        )
        if esc.category == "safety":
            text += "\nDemi keselamatan, jauhkan diri dari charger dan kendaraan. Jika ada api atau bahaya langsung, hubungi 112."
        return text
    if created:
        return f"Terima kasih. Laporan Anda sudah dicatat (tiket #{ticket_id}) dan akan ditindaklanjuti tim Enerva."
    return f"Laporan Anda sebelumnya sudah kami terima (tiket #{ticket_id}) dan sedang ditindaklanjuti."
"""CONTOH DATA. Ganti dengan informasi resmi Enerva sebelum dipakai customer sungguhan."""
import re

FAQ = [
    ("jam buka operasional 24 jam", "Stasiun Enerva Sunset Road beroperasi 24 jam. (contoh data)"),
    ("wifi gratis password akses", "Wi-Fi gratis 30 menit tersedia setelah registrasi. (contoh data)"),
    ("poin reward tukar redeem", "Poin dihitung dari kWh charging dan bisa ditukar di katalog reward. (contoh data)"),
    ("harga tarif biaya per kwh", "Tarif mengikuti struk charging di aplikasi/charger. (contoh data)"),
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def search(query: str, top: int = 2) -> list[str]:
    q = _tokens(query)
    scored = sorted(((len(q & _tokens(k)), a) for k, a in FAQ), reverse=True)
    return [a for score, a in scored[:top] if score > 0]
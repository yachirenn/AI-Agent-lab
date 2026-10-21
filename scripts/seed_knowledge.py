"""Seed knowledge base resmi Enerva ke PostgreSQL lengkap dengan representasi vektor embedding.
Pemakaian:
    python -m scripts.seed_knowledge
    python -m scripts.seed_knowledge --reindex
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from app.agent import knowledge
from app.db import repo

from dotenv import load_dotenv
load_dotenv()
from app.logging_config import setup_logging
setup_logging()
log = logging.getLogger("seed_knowledge")

ARTICLES: list[dict[str, Any]] = [
    {
        "slug": "jam-operasional-sunset-road",
        "title": "Jam Operasional & Akses Stasiun Sunset Road",
        "category": "station",
        "content": (
            "Stasiun Pengisian Enerva Sunset Road berlokasi di Jl. Sunset Road No. 88, Kuta, Bali. "
            "Stasiun beroperasi selama 24 jam penuh setiap hari, termasuk akhir pekan dan hari libur nasional. "
            "Area stasiun memiliki penerangan terang, dipantau CCTV 24 jam, dan dijaga petugas keamanan serta teknisi stasiun."
        ),
        "metadata": {"station_code": "sunset-road", "open_hours": "24/7"},
    },
    {
        "slug": "fasilitas-stasiun-sunset-road",
        "title": "Fasilitas Pengemudi Stasiun Sunset Road",
        "category": "station",
        "content": (
            "Stasiun Enerva Sunset Road menyediakan fasilitas lengkap untuk kenyamanan pengemudi saat menunggu: "
            "Driver Lounge ber-AC, kursi istirahat nyaman, toilet bersih, musholla, dispenser air minum isi ulang gratis, "
            "cafe mitra dengan diskon khusus driver, serta akses Wi-Fi berkecepatan tinggi gratis 30 menit (SSID: Enerva-Guest)."
        ),
        "metadata": {"station_code": "sunset-road", "wifi": True},
    },
    {
        "slug": "spesifikasi-charger-konektor",
        "title": "Tipe Charger dan Spesifikasi Konektor",
        "category": "station",
        "content": (
            "Enerva Sunset Road memiliki total 4 unit dispenser pengisian: "
            "2 unit DC Ultra-Fast Charger 120 kW dengan konektor ganda CCS2 (dukungan pengisian 20%-80% dalam waktu 25-35 menit), "
            "1 unit DC Fast Charger 60 kW (CCS2), dan 1 unit AC Charger 22 kW (Type 2). "
            "Kompatibel penuh dengan seluruh kendaraan listrik di Indonesia seperti Hyundai (Ioniq 5, Ioniq 6, Kona), "
            "BYD (Seal, Atto 3, Dolphin, M6), Wuling (Air EV, Binguo EV, Cloud EV), MG, Chery, Kia, dan Tesla (dengan adaptor CCS2)."
        ),
        "metadata": {"station_code": "sunset-road", "charger_types": ["DC 120kW", "DC 60kW", "AC 22kW"]},
    },
    {
        "slug": "jam-operasional-sanur-hub",
        "title": "Jam Operasional & Fasilitas Stasiun Sanur Port Hub",
        "category": "station",
        "content": (
            "Stasiun Enerva Sanur Port Hub berlokasi di Jl. Bypass Ngurah Rai No. 12, Sanur, Denpasar Selatan (dekat dermaga Sanur). "
            "Beroperasi selama 24 jam setiap hari dengan 2 unit DC Fast Charger 120 kW (CCS2) dan 1 unit AC Charger 22 kW (Type 2). "
            "Fasilitas mencakup driver lounge ber-AC, toilet bersih, dispenser air minum, Wi-Fi gratis, serta lokasi bersebelahan dengan minimarket 24 jam."
        ),
        "metadata": {"station_code": "sanur-hub", "open_hours": "24/7", "charger_types": ["DC 120kW", "AC 22kW"]},
    },
    {
        "slug": "jam-operasional-ubud-central",
        "title": "Jam Operasional & Fasilitas Stasiun Ubud Monkey Forest",
        "category": "station",
        "content": (
            "Stasiun Enerva Ubud Monkey Forest berlokasi di Jl. Wenara Wana, Padangtegal, Ubud, Gianyar. "
            "Beroperasi pukul 06.00 hingga 23.00 WITA. Dilengkapi 1 unit DC Fast Charger 60 kW (CCS2) dan 2 unit AC Charger 22 kW (Type 2). "
            "Menyediakan area istirahat terbuka bernuansa asri pedesaan Ubud, Wi-Fi gratis, toilet, serta kedai kopi lokal mitra Enerva."
        ),
        "metadata": {"station_code": "ubud-central", "open_hours": "06:00-23:00", "charger_types": ["DC 60kW", "AC 22kW"]},
    },
    {
        "slug": "jam-operasional-canggu-coastal",
        "title": "Jam Operasional & Fasilitas Stasiun Canggu Shortcut",
        "category": "station",
        "content": (
            "Stasiun Enerva Canggu Shortcut berlokasi di Jl. Pantai Berawa No. 45, Canggu, Kuta Utara. "
            "Beroperasi 24 jam setiap hari. Menyediakan 2 unit DC Ultra-Fast Charger 120 kW (CCS2) dan 1 unit AC Charger 22 kW. "
            "Fasilitas lengkap: coworking lounge ber-AC, koneksi internet Wi-Fi gigabit, cafe, musholla, dan area parkir luas."
        ),
        "metadata": {"station_code": "canggu-coastal", "open_hours": "24/7", "charger_types": ["DC 120kW", "AC 22kW"]},
    },
    {
        "slug": "jam-operasional-airport-hub",
        "title": "Jam Operasional & Fasilitas Stasiun Ngurah Rai Hub",
        "category": "station",
        "content": (
            "Stasiun Enerva Ngurah Rai Hub berlokasi di Jl. Raya Tuban No. 1, berdekatan dengan Bandara Internasional I Gusti Ngurah Rai. "
            "Beroperasi 24 jam nonstop untuk melayani armada taksi listrik, rental, dan kendaraan pribadi. "
            "Dilengkapi 2 unit DC Ultra-Fast Charger 180 kW (CCS2) pengisian super cepat dan 2 unit AC 22 kW. "
            "Fasilitas: shower room/kamar mandi pengemudi, rest area express, musholla, dan kantin pengemudi."
        ),
        "metadata": {"station_code": "airport-hub", "open_hours": "24/7", "charger_types": ["DC 180kW", "AC 22kW"]},
    },
    {
        "slug": "tarif-dan-biaya-charging",

        "title": "Tarif Pengisian Daya dan Biaya per kWh",
        "category": "pricing",
        "content": (
            "Tarif resmi pengisian daya Enerva Sunset Road: "
            "1. DC Fast & Ultra-Fast Charging (CCS2): Rp 2.475 per kWh. "
            "2. AC Standard Charging (Type 2): Rp 1.650 per kWh. "
            "Semua transaksi dikenakan PPN 11% sesuai regulasi pemerintah dan biaya administrasi layanan Rp 2.500 per sesi transaksi. "
            "Rincian kWh dan total biaya tertera secara transparan di layar charger dan struk digital."
        ),
        "metadata": {"price_dc_kwh": 2475, "price_ac_kwh": 1650, "currency": "IDR"},
    },
    {
        "slug": "metode-pembayaran-resmi",
        "title": "Metode Pembayaran Pengisian Daya",
        "category": "pricing",
        "content": (
            "Enerva mendukung berbagai metode pembayaran instan nontunai: "
            "1. QRIS Nasional (GoPay, OVO, DANA, ShopeePay, LinkAja, BCA, Mandiri Livin, BRImo). "
            "2. Kartu Kredit dan Debit berlogo Visa atau Mastercard melalui mesin EDC stasiun. "
            "3. Saldo akun aplikasi Enerva yang dapat di-topup kapan saja."
        ),
        "metadata": {"methods": ["QRIS", "Credit Card", "Debit Card", "E-Wallet"]},
    },
    {
        "slug": "program-poin-loyalitas",
        "title": "Perhitungan Poin Loyalitas Pelanggan",
        "category": "points",
        "content": (
            "Setiap pengisian daya di stasiun Enerva menghasilkan poin loyalitas secara otomatis dengan rasio 1 kWh = 10 poin. "
            "Sebagai contoh, pengisian 42,3 kWh menghasilkan 423 poin. "
            "Poin langsung masuk ke buku besar (points ledger) setelah sesi selesai dan tidak memiliki masa kedaluwarsa "
            "selama pelanggan aktif melakukan pengisian daya minimal satu kali dalam 12 bulan."
        ),
        "metadata": {"points_per_kwh": 10},
    },
    {
        "slug": "penukaran-poin-reward",
        "title": "Katalog Penukaran Poin Reward",
        "category": "points",
        "content": (
            "Poin reward dapat ditukar melalui staf stasiun atau bot percakapan Enerva: "
            "- 300 poin: Voucher kopi/snack gratis di cafe mitra Sunset Road. "
            "- 500 poin: Voucher potongan charging senilai Rp 50.000. "
            "- 900 poin: Voucher potongan charging senilai Rp 100.000. "
            "- 1.500 poin: Merchandise eksklusif Enerva (kaos polo, tumbler, atau payung golf)."
        ),
        "metadata": {"rewards_available": True},
    },
    {
        "slug": "panduan-konektor-terkunci",
        "title": "Panduan Mengatasi Konektor Charger yang Terkunci",
        "category": "troubleshooting",
        "content": (
            "Jika konektor charger CCS2 tidak bisa dilepas setelah pengisian selesai: "
            "1. Pastikan proses charging sudah selesai atau dihentikan dari tombol 'Stop' di layar mesin charger. "
            "2. Buka kunci (unlock) pintu mobil 2-3 kali berturut-turut menggunakan remote kunci mobil untuk merilis motor pengunci port charging. "
            "3. Jangan menarik kabel secara paksa. Jika masih macet, gunakan tuas penarik darurat port charger (Emergency Release Pin) "
            "di ruang bagasi belakang kendaraan Anda sesuai buku pedoman pabrikan mobil."
        ),
        "metadata": {"troubleshoot": "connector_lock"},
    },
    {
        "slug": "prosedur-keadaan-darurat",
        "title": "Prosedur Keselamatan dan Tanggap Darurat",
        "category": "troubleshooting",
        "content": (
            "Apabila Anda melihat percikan api, kepulan asap, bau gosong, atau air menggenangi area dispenser: "
            "1. Segera tekan tombol Emergency Stop (tombol merah besar berputar) di samping dispenser pengisian untuk memutus arus tegangan tinggi. "
            "2. Jauhi kendaraan dan charger minimal jarak 10 meter. "
            "3. Kirim pesan dengan kata 'DARURAT' di chat ini untuk memicu notifikasi darurat ke tim operasional, atau segera hubungi 112 / petugas keamanan stasiun."
        ),
        "metadata": {"emergency": True},
    },
    {
        "slug": "jangkauan-layanan-dan-ekspansi-wilayah",
        "title": "Jangkauan Wilayah Operasional dan Rencana Ekspansi Jaringan Enerva",
        "category": "station",
        "content": (
            "Jaringan stasiun pengisian kendaraan listrik (SPKLU) Enerva saat ini aktif melayani area Bali di 5 titik strategis: "
            "1. Enerva Sunset Road (Kuta) - 24 Jam. "
            "2. Enerva Canggu Shortcut (Canggu) - 24 Jam. "
            "3. Enerva Sanur Port Hub (Sanur) - 24 Jam. "
            "4. Enerva Ngurah Rai Hub (Tuban/Bandara) - 24 Jam. "
            "5. Enerva Ubud Monkey Forest (Ubud) - 06.00-23.00 WITA. "
            "Wilayah lain di luar Bali (termasuk Sleman, Yogyakarta, Solo, Semarang, Surabaya, dan Jakarta) saat ini belum memiliki stasiun pengisian aktif Enerva. "
            "Sistem Enerva secara otomatis menghimpun data rute dan domisili pelanggan di luar Bali sebagai bahan studi kelayakan prioritas ekspansi jaringan stasiun di masa mendatang."
        ),
        "metadata": {"coverage": ["Bali"], "expansion_pipeline": ["Yogyakarta", "Sleman", "Surabaya", "Jakarta"]},
    },
    {
        "slug": "waktu-operasional-dan-layanan-realtime",
        "title": "Waktu Operasional Stasiun dan Monitoring Sistem Real-Time",
        "category": "station",
        "content": (
            "Mayoritas stasiun Enerva (Sunset Road, Canggu, Sanur, Airport) beroperasi 24 jam penuh setiap hari, termasuk hari libur nasional, "
            "sedangkan stasiun Ubud Monkey Forest beroperasi pukul 06.00 hingga 23.00 WITA. "
            "Seluruh transaksi, pencatatan kWh, dan perolehan poin loyalitas diproses secara real-time langsung ke akun pelanggan setelah pengisian selesai. "
            "Asisten virtual AI Enerva siap sedia melayani pertanyaan, bantuan teknis, dan informasi stasiun 24/7 non-stop."
        ),
        "metadata": {"realtime_support": True, "open_hours": "24/7"},
    },
]


def seed(reindex: bool = False) -> None:
    log.info("memulai proses seeding %d artikel knowledge base...", len(ARTICLES))
    success = 0
    for art in ARTICLES:
        existing = repo.get_knowledge_item(art["slug"])
        if existing and not reindex:
            log.info("artikel '%s' sudah ada (skip, gunakan --reindex untuk menimpa)", art["slug"])
            success += 1
            continue

        res = knowledge.upsert_document(
            slug=art["slug"],
            title=art["title"],
            category=art["category"],
            content=art["content"],
            metadata=art["metadata"],
        )
        log.info("tersimpan artikel '%s' (id=%s, category=%s)", res["slug"], res["id"], res["category"])
        success += 1

    total = repo.count_knowledge_items()
    log.info("seeding selesai! Total artikel di database: %d", total)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Knowledge Base Enerva")
    parser.add_argument("--reindex", action="store_true", help="Paksa timpa dan re-embed seluruh artikel")
    args = parser.parse_args()
    seed(reindex=args.reindex)

import hmac
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # agar `import app` jalan dari Streamlit

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
from app.db import repo  # noqa: E402
from app.services import customer360  # noqa: E402
from app.agent import knowledge  # noqa: E402

WIB = ZoneInfo("Asia/Jakarta")
st.set_page_config(page_title="Enerva Intelligence", layout="wide")


def require_login() -> None:
    expected = os.environ.get("DASHBOARD_PASSWORD", "")
    if not expected:
        st.error("DASHBOARD_PASSWORD belum diisi di .env. Dashboard menolak berjalan tanpa password.")
        st.stop()
    if st.session_state.get("authed"):
        return
    entered = st.text_input("Password", type="password")
    if entered:
        if hmac.compare_digest(entered.encode(), expected.encode()):
            st.session_state["authed"] = True
            st.rerun()
        st.error("Password salah.")
    st.stop()


def fmt(dt: datetime | None) -> str:
    return dt.astimezone(WIB).strftime("%d %b %Y %H:%M") if dt else "-"


def pct(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "-"


@st.cache_data(ttl=30)
def load_overview(days: int):
    return (
        repo.dashboard_kpis(days),
        repo.sessions_by_hour(days),
        repo.sessions_by_station(days),
        repo.customer_breakdown("driver_type"),
        repo.customer_breakdown("home_area"),
    )


require_login()
st.title("⚡ Enerva Customer Intelligence")
tab_overview, tab_customers, tab_inactive, tab_tickets, tab_kb = st.tabs(
    ["Ringkasan", "Customer 360°", "Inaktivitas", "Antrean CS", "Knowledge Base (RAG)"]
)

with tab_overview:
    days = st.select_slider("Periode (hari terakhir)", options=[7, 14, 30, 60, 90], value=30)
    k, by_hour, by_station, by_driver, by_area = load_overview(days)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customer terdaftar", k["registered"])
    c2.metric("Driver aktif", k["active_drivers"])
    c3.metric("Total kWh", f"{k['total_kwh']:,.0f}")
    c4.metric("Repeat rate", pct(k["repeat_drivers"], k["active_drivers"]), help="Driver aktif dengan ≥ 2 sesi")
    c5, c6, c7 = st.columns(3)
    c5.metric("Retention", pct(k["retained"], k["prev_active"]), help="Aktif di periode sebelumnya dan masih aktif sekarang")
    c6.metric("Tiket terbuka", k["open_tickets"], delta=f"{k['urgent_tickets']} urgent", delta_color="inverse")
    c7.metric("Alert inaktivitas", k["inactivity_alerts"])

    hours = pd.Series({r["hour"]: r["sessions"] for r in by_hour}).reindex(range(24), fill_value=0)
    left, right = st.columns(2)
    left.subheader("Sesi per jam (WIB)")
    left.bar_chart(hours)
    right.subheader("kWh per stasiun")
    if by_station:
        right.bar_chart(pd.DataFrame(by_station).set_index("station")["kwh"])
    else:
        right.info("Belum ada data.")
    left, right = st.columns(2)
    left.subheader("Customer per tipe driver")
    if by_driver:
        left.bar_chart(pd.DataFrame(by_driver).set_index("label"))
    right.subheader("Customer per area tinggal")
    if by_area:
        right.bar_chart(pd.DataFrame(by_area).set_index("label"))

with tab_customers:
    search = st.text_input("Cari nama atau Customer ID", max_chars=40)
    rows = repo.customer_list(search.strip(), 100)
    if not rows:
        st.info("Tidak ada customer yang cocok.")
    else:
        df = pd.DataFrame(rows)
        df["last_visit"] = df["last_visit"].map(fmt)
        st.dataframe(df, use_container_width=True, hide_index=True)

        code = st.selectbox("Lihat profil 360°", [r["customer_code"] for r in rows])
        p = customer360.get(code)
        if p:
            st.subheader(f"{p['name'] or '-'} ({p['customer_code']})")
            a, b, c = st.columns(3)
            a.metric("Status", p["status"])
            b.metric("Churn risk", p["churn_risk"])
            c.metric("Poin", f"{p['points']:,}")
            left, right = st.columns(2)
            left.write(
                {
                    "Kendaraan": ", ".join(p["vehicles"]) or "-",
                    "Tipe driver": p["driver_type"] or "-",
                    "Area tinggal": p["home_area"] or "-",
                    "Rute utama": p["main_route"] or "-",
                    "Consent promo": "ya" if p["consent_marketing"] else "tidak",
                }
            )
            right.write(
                {
                    "kWh/hari (Enerva)": round(p["kwh_per_day"], 1),
                    "kWh/minggu (Enerva)": round(p["kwh_per_week"], 1),
                    "kWh/30 hari (Enerva)": round(p["kwh_30d"], 1),
                    "Kunjungan/minggu": round(p["visits_per_week"], 1),
                    "Jam favorit": p["preferred_time"] or "-",
                    "Stasiun favorit": p["preferred_station"] or "-",
                    "Kunjungan terakhir": fmt(p["last_visit"]),
                }
            )
            st.write(
                "**Preferensi dari percakapan:**", p["preferred_station"] or "belum ada"
            )

with tab_inactive:
    alerts = repo.open_inactivity_alerts()
    if not alerts:
        st.success("Tidak ada alert inaktivitas terbuka.")
    else:
        df = pd.DataFrame(alerts).drop(columns=["id", "customer_id"])
        for col in ("last_visit_at", "retention_sent_at", "detected_at"):
            df[col] = df[col].map(fmt)
        df["median_gap_hours"] = df["median_gap_hours"].astype(float)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("consent_marketing = false: pesan retensi tidak dikirim otomatis, perlu tindak lanjut manusia.")

with tab_tickets:
    tickets = repo.ticket_queue()
    if not tickets:
        st.success("Antrean kosong.")
    else:
        df = pd.DataFrame(tickets)
        df["created_at"] = df["created_at"].map(fmt)
        st.dataframe(df, use_container_width=True, hide_index=True)   # teks customer tampil sebagai teks biasa

with tab_kb:
    st.subheader("📚 Knowledge Base & Semantic Search (RAG)")
    test_q = st.text_input("Uji Pencarian Pertanyaan Customer", placeholder="Contoh: bisa bayar pakai qris?")
    if test_q:
        results = knowledge.search_detailed(test_q, top=3)
        if results:
            st.write(f"Ditemukan **{len(results)} artikel** paling relevan:")
            for r in results:
                score = r.get("score", 0.0)
                sim = r.get("similarity", 0.0)
                cat = r.get("category", "general").upper()
                with st.expander(f"[{cat}] {r['title']} — Skor Relevansi: {score:.2f} (Kemiripan Vektor: {sim:.2f})", expanded=True):
                    st.write(r["content"])
                    st.caption(f"Slug: `{r.get('slug')}` | Kategori: `{r.get('category')}`")
        else:
            st.warning("Tidak ada artikel yang cocok dengan ambang batas kemiripan.")

    st.divider()
    cat_filter = st.selectbox("Filter Kategori Artikel", ["Semua", "station", "pricing", "points", "troubleshooting", "faq"])
    kb_items = repo.list_knowledge_items(None if cat_filter == "Semua" else cat_filter)
    if kb_items:
        df_kb = pd.DataFrame(kb_items)[["slug", "title", "category", "content"]]
        st.dataframe(df_kb, use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada artikel dalam kategori ini.")
        
with st.expander("Sistem: antrean pengiriman"):
    stats = repo.outbox_stats()
    if stats:
        st.dataframe(pd.DataFrame(stats), use_container_width=True, hide_index=True)
    else:
        st.caption("Outbox kosong.")
    dead = repo.dead_outbox()
    if any(d["kind"] == "staff_alert" for d in dead):
        st.error("Ada ALERT STAF yang gagal terkirim permanen. Hubungi staf lewat jalur lain.")
    if dead:
        st.dataframe(pd.DataFrame(dead), use_container_width=True, hide_index=True)
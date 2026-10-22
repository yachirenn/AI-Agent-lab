# ⚡ Enerva AI (`ai-agent-lab`)

> **Autonomous AI Customer Support & Customer Intelligence for EV Charging Station Ecosystem**

Sistem operasional dan kecerdasan buatan terpadu untuk stasiun pengisian daya kendaraan listrik (**SPKLU**). Menggabungkan **ReAct AI Agent**, **RAG Semantik 768-dimensi**, **Pola Transactional Outbox**, integrasi **Telegram & WhatsApp Cloud API**, pendaftaran otomatis berbasis **FSM**, **Buku Besar Finansial (Append-only Ledger)**, deteksi inaktivitas & retensi otomatis, serta **Live Chat Handover Dua Arah** langsung dari dashboard admin.

---

## 🏛️ Arsitektur Sistem

```mermaid
flowchart TD
    subgraph Ingress ["Channel & Ingress"]
        WA["WhatsApp Cloud API (Meta Webhook)"]
        TG["Telegram Bot (Webhook / Polling)"]
        CMS["CMS Charger Webhook (kWh Events)"]
    end

    subgraph API ["FastAPI Layer (app/api/main.py)"]
        WA_EP["/webhook/whatsapp (HMAC SHA-256)"]
        TG_EP["/webhook/telegram (Secret Token)"]
        CMS_EP["/webhook/cms (X-CMS-Secret)"]
    end

    WA --> WA_EP
    TG --> TG_EP
    CMS --> CMS_EP

    subgraph Pipeline ["Service Pipeline (app/services/)"]
        direction TB
        FSM["Registration FSM (registration.py)"]
        ESC{"Escalation Rule Filter (escalation.py)"}
        PREF["Preference Learner (preferences.py)"]
        HANDOVER{"Active Handover Check?"}
        AGENT["ReAct AI Agent Loop (app/agent/loop.py)"]
        RAG["Semantic RAG Search (app/agent/knowledge.py)"]
        TOOLS["Tool Execution Context (app/agent/tools.py)"]
        CHARGING["Charging Ingest (app/services/charging.py)"]
    end

    WA_EP --> Pipeline
    TG_EP --> Pipeline
    CMS_EP --> CHARGING

    ESC -- "Level 3: Safety / Fire / Emergency" --> OUTBOX
    ESC -- "Level 1: Normal Query" --> HANDOVER
    HANDOVER -- "In Progress" --> STAF_PAUSE["Tahan AI & Beri Tahu Staf"]
    HANDOVER -- "No Handover" --> AGENT
    AGENT <--> TOOLS
    TOOLS <--> RAG

    subgraph Outbox ["Reliable Messaging Pattern"]
        OUTBOX[("outbox Table")]
        WORKER["Outbox Worker (scripts/outbox_worker.py)"]
        DISPATCHER["Dispatcher (dispatcher.py)"]
        OUTBOX --> WORKER --> DISPATCHER --> WA & TG
    end

    subgraph Storage ["Database Layer (PostgreSQL 16+)"]
        LEDGER[("points_ledger (Append-only)")]
        KB[("knowledge_base (Vector Embeddings)")]
        TICKETS[("cs_tickets")]
        CUSTOMERS[("customers & identities")]
        CONV[("conversations")]
    end

    Pipeline --> Storage

    subgraph Dashboard ["Streamlit Intelligence (dashboard/app.py)"]
        KPI["Station KPIs & Customer 360°"]
        TICKETS_UI["Live Chat Handover Workspace"]
        RAG_UI["Semantic Search Tester"]
    end

    Storage <--> Dashboard
```

---

## 🌟 Fitur Utama

1. **Multi-Channel Support (Telegram & WhatsApp)**:
   - Dukungan penuh untuk bot Telegram dan **WhatsApp Business Cloud API** resmi (Meta Graph API).
   - Verifikasi tanda tangan digital `X-Hub-Signature-256` dan *handshake challenge*.
   - Onboarding via QR code stasiun (contoh: `https://wa.me/<nomor>?text=MULAI%20sunset-road`).
2. **Keamanan & Proteksi Prompt Injection**:
   - `ToolContext(customer_id)` diinjeksi di tingkat backend server, bukan dari argumen yang dibuat oleh LLM. Pengguna tidak dapat memanipulasi prompt untuk mencuri atau mengubah data pelanggan lain.
   - Whitelist ketat pada pembaruan kolom SQL (`_CUSTOMER_FIELDS`, `_BREAKDOWN_DIMS`) kebal *SQL Injection*.
3. **Penyelamatan Darurat Deterministik (Level 3 Bypass)**:
   - Isu darurat (kebakaran, sengatan listrik, mobil mogok, kabel macet, masalah pembayaran ganda) dipotong langsung di layer Regex sebelum menyentuh LLM, menghindari halusinasi atau latensi AI.
4. **Knowledge Base Semantik (RAG - Retrieval-Augmented Generation)**:
   - Dokumen stasiun, konektor CCS2, tarif kWh, dan SOP diubah ke vektor 768-dimensi menggunakan **Gemini Embeddings** (`gemini-embedding-001`).
   - *Hybrid search* menggabungkan *cosine similarity* dengan *lexical boost* serta fallback leksikal GIN Index PostgreSQL.
5. **Live Chat Handover Dua Arah (Human-in-the-Loop)**:
   - Staf CS dapat memantau antrean tiket di Dashboard Streamlit, membaca riwayat obrolan pelanggan (tampilan chat bubble `st.chat_message`), dan mengetik balasan langsung ke Telegram/WhatsApp pelanggan.
   - Saat tiket berstatus `in_progress`, respon otomatis bot AI dihentikan sementara agar tidak membingungkan pelanggan.
6. **Keandalan Finansial (Append-Only Ledger)**:
   - Poin dihitung dengan tipe data Python `Decimal` dengan pembulatan ke bawah (`ROUND_DOWN`).
   - Saldo dihitung menggunakan `SUM(delta)` pada tabel `points_ledger` tanpa operasi `UPDATE`, mencegah *race condition* dan manipulasi saldo.
7. **Pola Transactional Outbox (Zero Message Loss)**:
   - Seluruh notifikasi kritis (struk charging, tiket darurat staf) ditulis ke tabel `outbox` dalam transaksi atomik database.
   - Worker mandiri mengirim pesan dengan *exponential backoff + jitter* dan *Dead Letter Queue* (DLQ).
8. **Deteksi Inaktivitas & Retensi Beretika**:
   - Mendeteksi penurunan ritme kunjungan pengemudi berbasis kalkulasi `median_gap_hours` individual.
   - Mematuhi etika pengiriman: *quiet hours* (hanya dikirim jam 08:00 - 20:00 WIB) dan kepatuhan privasi GDPR/PDP (`/stop`, `/subscribe`, `/preferensi`).

---

## 📁 Struktur Direktori

```text
ai-agent-lab/
├── app/
│   ├── agent/                 # Otak AI Agent, LLM Fallback, & RAG
│   │   ├── embeddings.py      # Gemini & Mock Embedders (768 dimensi)
│   │   ├── knowledge.py       # RAG Knowledge Base & Hybrid Search
│   │   ├── llm_client.py      # Multi-Provider Client (Gemini, Groq, OpenRouter) + Circuit Breaker
│   │   ├── loop.py            # ReAct Agent Loop dengan Persona ramah ("Kak")
│   │   └── tools.py           # Toolset terisolasi dengan ToolContext
│   ├── api/                   # Webhook & REST Endpoints
│   │   └── main.py            # FastAPI App (Telegram, WhatsApp, CMS)
│   ├── channels/              # Adapter Platform Pesan
│   │   ├── base.py            # Abstraksi InboundMessage
│   │   ├── telegram.py        # Telegram Bot API adapter
│   │   └── whatsapp.py        # Meta WhatsApp Cloud API adapter
│   ├── db/                    # Data Layer & Database Repository
│   │   ├── migrations/        # SQL Migrations (002 s/d 013)
│   │   ├── repo.py            # Single Source of Truth akses PostgreSQL
│   │   └── schema.sql         # Skema inisial database
│   ├── services/              # Logika Bisnis & Servis Operasional
│   │   ├── alerts.py          # Notifikasi darurat staf
│   │   ├── charging.py        # Pengolahan transaksi charging dari CMS
│   │   ├── customer360.py     # Metrik profiling Customer 360° & Churn Risk
│   │   ├── dispatcher.py      # Single-point pengiriman pesan keluar
│   │   ├── escalation.py      # Rule-based filter darurat & pembuat tiket
│   │   ├── handover.py        # Live Chat Handover dua arah staf CS
│   │   ├── handler.py         # Router pesan masuk & manajemen status
│   │   ├── inactivity.py      # Deteksi ritme pengemudi & pesan retensi
│   │   ├── loyalty.py         # Perhitungan poin berbasis Decimal
│   │   ├── pipeline.py        # Pipeline pemrosesan pesan inbound
│   │   ├── preferences.py     # Ekstraksi preferensi personal beretika
│   │   └── registration.py    # FSM alur registrasi multi-tahap
│   ├── logging_config.py      # Konfigurasi JSON structured logging
│   └── schemas.py             # Pydantic kontrak data validasi event CMS
├── dashboard/
│   └── app.py                 # Streamlit Customer Intelligence & CS Workspace
├── evals/                     # Dataset evaluasi performa dan keamanan agent
├── scripts/                   # CLI Tools & Background Workers
│   ├── ask.py                 # Tes interaksi langsung CLI ke agent
│   ├── cms_feeder.py          # Mock event generator transaksi CMS
│   ├── eval_agent.py          # Automated evaluation runner dengan LLM Judge
│   ├── outbox_worker.py       # Background worker pengiriman pesan outbox
│   ├── poll.py                # Telegram Long Polling untuk dev lokal
│   ├── run_inactivity.py      # Eksekutor job deteksi inaktivitas sekali jalan
│   ├── scheduler.py           # Cron scheduler harian inaktivitas (APScheduler)
│   ├── seed_history.py        # Generator data charging histori simulasi
│   ├── seed_knowledge.py      # Seeder dokumen resmi knowledge base RAG
│   └── set_webhook.py         # Skrip pendaftaran webhook Telegram
├── tests/                     # Rangkaian Pengujian Otomatis (116 Test Cases)
├── docker-compose.yml         # Container PostgreSQL 16 + pgvector
├── pytest.ini                 # Konfigurasi pengujian pytest
└── requirements.txt           # Dependensi Python
```

---

## 🚀 Panduan Memulai (Quickstart)

### 1. Kebutuhan Sistem (Prerequisites)
* **Python 3.12+**
* **PostgreSQL 16+** (bisa menggunakan Docker Compose atau instalasi native)

### 2. Pemasangan Dependensi
Buat virtual environment dan pasang pustaka yang dibutuhkan:
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Konfigurasi Lingkungan (`.env`)
Salin file `.env.example` menjadi `.env`:
```powershell
copy .env.example .env
```
Lalu lengkapi konfigurasi variabel lingkungan:
```env
# Database PostgreSQL
DATABASE_URL=postgresql://enerva:GANTI_DENGAN_PASSWORD@localhost:5432/enerva

# Telegram Bot
TELEGRAM_BOT_TOKEN=token_dari_botfather
TELEGRAM_WEBHOOK_SECRET=rahasia_webhook_telegram
STAFF_TELEGRAM_CHAT_ID=id_chat_grup_staf

# WhatsApp Cloud API (Opsional)
WHATSAPP_VERIFY_TOKEN=token_verifikasi_bebas
WHATSAPP_APP_SECRET=app_secret_dari_meta
WHATSAPP_ACCESS_TOKEN=access_token_dari_meta
WHATSAPP_PHONE_NUMBER_ID=phone_number_id_dari_meta
WHATSAPP_API_VERSION=v20.0

# CMS Charger
CMS_WEBHOOK_SECRET=token_rahasia_cms
POINTS_PER_KWH=10

# Model AI (Google Gemini)
GEMINI_API_KEY=api_key_dari_google_ai_studio
LLM_MODEL=gemini-3.5-flash-lite

# Keamanan Dashboard
DASHBOARD_PASSWORD=password_akses_dashboard_anda
```

### 4. Menjalankan Database & Migrasi
Jika menggunakan Docker:
```powershell
docker compose up -d
```
Terapkan berkas migrasi database secara berurutan:
```powershell
# Jalankan migrasi di database postgres Anda:
# app/db/schema.sql
# app/db/migrations/002_registration.sql
# app/db/migrations/003_escalation.sql
# app/db/migrations/004_inactivity.sql
# app/db/migrations/005_knowledge_base.sql
# app/db/migrations/006_preferences.sql
# app/db/migrations/007_outbox.sql
# app/db/migrations/008_multi_stations.sql
# app/db/migrations/009_staff_actions.sql
# app/db/migrations/010_outbox_reply.sql
# app/db/migrations/011_inbox.sql
# app/db/migrations/012_inbox_result.sql
# app/db/migrations/013_inbox_claim_token.sql
```

### 5. Seeding Data Knowledge Base (RAG)
Muat seluruh dokumen operasional resmi Enerva dan buat representasi vektor embedding-nya:
```powershell
python -m scripts.seed_knowledge --reindex
```

---

## 🏃 Menjalankan Aplikasi

Jalankan komponen-komponen berikut di jendela terminal terpisah:

### A. Server API (FastAPI)
Menerima webhook dari Telegram, WhatsApp, dan CMS Charger:
```powershell
uvicorn app.api.main:app --port 8000 --reload
```

### B. Outbox Background Worker
Mengirim pesan keluar, notifikasi charging, dan alert staf secara andal:
```powershell
python -m scripts.outbox_worker
```

### C. Inactivity Retention Scheduler
Menjalankan pemeriksaan driver inaktif secara berkala setiap hari jam 10:00 WIB:
```powershell
python -m scripts.scheduler
```

### D. Dashboard Customer Intelligence (Streamlit)
Menampilkan visualisasi data stasiun, analitik pelanggan, penguji RAG, dan antarmuka Live Chat Handover:
```powershell
streamlit run dashboard/app.py
```

### E. Telegram Local Polling (Mode Pengembangan)
Jika menguji Telegram di komputer lokal tanpa public IP / tunnel:
```powershell
python -m scripts.poll
```

### F. Enerva MCP Server (Model Context Protocol)
Menghubungkan ekosistem Enerva dengan AI desktop staf (Claude Desktop, Cursor, Antigravity IDE):
```powershell
# Jalankan server MCP (stdio transport)
mcp run scripts/mcp_server.py

# Atau inspeksi interaktif via MCP Dev Inspector
mcp dev scripts/mcp_server.py
```
* **Tools (11 Tools)**: `overview`, `list_stations`, `station_performance`, `list_inactive_customers`, `open_tickets`, `customer_360`, `churn_risk_analysis`, `preference_summary`, `search_knowledge_base`, `reply_ticket`, `resolve_ticket`.
* **Resources (3 URIs)**: `enerva://stations`, `enerva://kpis/overview`, `enerva://sop/emergency`.
* **Prompts (3 Templates)**: `incident_triage`, `daily_executive_standup`, `customer_retention_pitch`.

---

## 🧪 Pengujian & Evaluasi

### Menjalankan Automated Test Suite (Pytest)
Proyek ini dilengkapi **140 skenario pengujian otomatis** yang mencakup pengujian konkurensi, idempotensi, race conditions, formula finansial, RAG search, live handover, multi-station, dan MCP server:
```powershell
pytest
```

### Menjalankan Evaluasi Perilaku AI Agent (Evals)
Menjalankan 26 kasus uji evaluasi perilaku agent (uji prompt injection, batasan data, empati persona, dan penilaian otomatis *LLM-as-a-Judge*):
```powershell
python -m scripts.eval_agent --judge
```
Hasil evaluasi akan disimpan otomatis dalam format JSON di direktori `evals/results/`.

---

## 📜 Lisensi
Dikembangkan untuk ekosistem operasional stasiun pengisian kendaraan listrik Enerva.


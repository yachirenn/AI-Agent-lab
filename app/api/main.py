from contextlib import asynccontextmanager
import hmac
import json
import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from app.channels import telegram, whatsapp
from app.db import repo
from app.logging_config import setup_logging
from app.schemas import ChargingEvent
from app.services import charging


def _enqueue_to_inbox(msg: Any, *, channel_label: str) -> None:
    """Simpan satu pesan masuk ke Inbox. psycopg bersifat blocking, jadi endpoint async
    memanggil fungsi ini lewat run_in_threadpool agar event loop tidak tersendat."""
    try:
        repo.enqueue_inbox(
            channel=msg.channel,
            user_id=msg.user_id,
            chat_id=msg.chat_id,
            message_id=msg.message_id,
            body=msg.text,
            is_start=msg.is_start,
            start_payload=msg.start_payload,
        )
    except Exception:
        logger.exception("gagal menyimpan pesan %s ke Inbox", channel_label)
        raise HTTPException(status_code=503, detail="Inbox sementara tidak tersedia")


async def _enqueue_whatsapp_messages(raw: bytes, signature: str | None, *, provider: str | None = None) -> None:
    secret = whatsapp.webhook_secret(provider) if provider else None
    if not whatsapp.verify_signature(raw, signature, secret=secret):
        raise HTTPException(status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400)

    for msg in whatsapp.parse_webhook(payload):
        await run_in_threadpool(_enqueue_to_inbox, msg, channel_label="WhatsApp")


setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Kelola lifecycle resource aplikasi: inisialisasi pool saat startup dan tutup saat shutdown."""
    logger.info("Aplikasi memulai: menginisialisasi connection pool database...")
    repo.get_pool()
    yield
    logger.info("Aplikasi berhenti: menutup connection pool database secara graceful...")
    repo.close_pool()


app = FastAPI(title="Enerva AI", lifespan=lifespan)



@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    expected = os.environ["TELEGRAM_WEBHOOK_SECRET"].encode()
    received = (x_telegram_bot_api_secret_token or "").encode()
    if not hmac.compare_digest(received, expected):
        raise HTTPException(status_code=403)

    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400)

    msg = telegram.parse_update(payload)
    if msg is not None:
        await run_in_threadpool(_enqueue_to_inbox, msg, channel_label="Telegram")

    return {"ok": True}
  
def require_cms_secret(x_cms_secret: str | None = Header(default=None)) -> None:
    expected = os.environ["CMS_WEBHOOK_SECRET"].encode()
    if not hmac.compare_digest((x_cms_secret or "").encode(), expected):
        raise HTTPException(status_code=403)


@app.post("/webhook/cms", dependencies=[Depends(require_cms_secret)])
def cms_webhook(event: ChargingEvent) -> dict:
    # `def` biasa (bukan async): psycopg bersifat blocking, jadi FastAPI menjalankannya di threadpool.
    try:
        result = charging.process_charging_event(event)
    except repo.UnknownStation:
        raise HTTPException(status_code=422, detail="station_code tidak dikenal")

    # Duplikat tetap 200: CMS harus berhenti me-retry.
    return {"status": result["status"], "points_awarded": result["points_awarded"]}


@app.get("/health/ready")
def ready() -> dict[str, bool]:
    try:
        repo.ping()
    except Exception:
        raise HTTPException(status_code=503)
    return {"ok": True}


@app.get("/webhook/whatsapp")
def whatsapp_verify(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    expected = os.environ.get("WHATSAPP_VERIFY_TOKEN", "")
    if mode == "subscribe" and expected and hmac.compare_digest((token or "").encode(), expected.encode()):
        return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403)


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, bool]:
    raw = await request.body()
    # Mendukung webhook Meta (WHATSAPP_APP_SECRET) maupun GOWA (WHATSAPP_WEBHOOK_SECRET)
    await _enqueue_whatsapp_messages(raw, x_hub_signature_256, provider=None)
    return {"ok": True}


@app.post("/webhook/whatsapp/gowa")
async def gowa_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, bool]:
    """Webhook GOWA; signature diverifikasi dengan secret GOWA khusus."""
    raw = await request.body()
    await _enqueue_whatsapp_messages(raw, x_hub_signature_256, provider="gowa")
    return {"ok": True}
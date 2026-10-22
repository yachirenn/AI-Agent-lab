from contextlib import asynccontextmanager
import hmac
import json
import logging
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.channels import telegram, whatsapp
from app.db import repo
from app.logging_config import setup_logging
from app.schemas import ChargingEvent
from app.services import charging

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
            logger.exception("gagal menyimpan pesan Telegram ke Inbox")
            raise HTTPException(status_code=503, detail="Inbox sementara tidak tersedia")

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
    if not whatsapp.verify_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400)

    for msg in whatsapp.parse_webhook(payload):
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
            logger.exception("gagal menyimpan pesan WhatsApp ke Inbox")
            raise HTTPException(status_code=503, detail="Inbox sementara tidak tersedia")

    return {"ok": True}
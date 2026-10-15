import hmac
import os
import json

from fastapi import Query
from fastapi.responses import PlainTextResponse
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request

from app.channels import whatsapp
from app.logging_config import setup_logging
from app.services import pipeline

from app.db import repo
from app.schemas import ChargingEvent
from app.services import charging
from app.services.pipeline import process_update

setup_logging()

app = FastAPI(title="Enerva AI")


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    background: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict[str, bool]:
    expected = os.environ["TELEGRAM_WEBHOOK_SECRET"].encode()
    received = (x_telegram_bot_api_secret_token or "").encode()
    if not hmac.compare_digest(received, expected):   # waktu konstan, anti timing attack
        raise HTTPException(status_code=403)

    background.add_task(process_update, await request.json())
    return {"ok": True}   # balas cepat; Telegram me-retry jika tidak dapat 200
  
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
    background: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict[str, bool]:
    raw = await request.body()               # signature dihitung dari byte mentah, bukan JSON hasil parse ulang
    if not whatsapp.verify_signature(raw, x_hub_signature_256):
        raise HTTPException(status_code=403)
    try:
        payload = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400)
    for msg in whatsapp.parse_webhook(payload):
        background.add_task(pipeline.process_message, msg)
    return {"ok": True}                      # balas cepat; Meta me-retry jika tidak mendapat 200
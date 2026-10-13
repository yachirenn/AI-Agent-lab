import hmac
import os

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request

from app.db import repo
from app.schemas import ChargingEvent
from app.services import charging
from app.services.pipeline import process_update

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
def cms_webhook(event: ChargingEvent, background: BackgroundTasks) -> dict:
    # `def` biasa (bukan async): psycopg bersifat blocking, jadi FastAPI menjalankannya di threadpool.
    try:
        result = charging.process_charging_event(event)
    except repo.UnknownStation:
        raise HTTPException(status_code=422, detail="station_code tidak dikenal")

    if result["status"] == "created" and result["customer_id"] is not None:
        background.add_task(charging.notify_customer, result, event.kwh)
    # Duplikat tetap 200: CMS harus berhenti me-retry.
    return {"status": result["status"], "points_awarded": result["points_awarded"]}
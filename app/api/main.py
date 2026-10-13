import hmac
import os

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

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
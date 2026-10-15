import os
import sys

from app.channels import telegram

if len(sys.argv) != 2:
    sys.exit("pemakaian: python -m scripts.set_webhook https://xxxx.trycloudflare.com")

base = sys.argv[1].rstrip("/")
telegram.set_webhook(f"{base}/webhook/telegram", os.environ["TELEGRAM_WEBHOOK_SECRET"])
print("webhook terpasang:", f"{base}/webhook/telegram")

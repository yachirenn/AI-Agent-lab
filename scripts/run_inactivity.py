import logging

from app.services import inactivity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
print(inactivity.run_once())
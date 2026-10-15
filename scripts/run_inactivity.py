import logging

from app.services import inactivity

from dotenv import load_dotenv
load_dotenv()
from app.logging_config import setup_logging
setup_logging()
print(inactivity.run_once())
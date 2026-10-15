"""Pemakaian: python -m scripts.ask ENV-000003 "poin saya berapa?" """
import logging
import sys

from app.agent.loop import run_agent
from app.db import repo

from dotenv import load_dotenv
load_dotenv()
from app.logging_config import setup_logging
setup_logging()
customer = repo.get_customer_by_code(sys.argv[1])
if customer is None:
    sys.exit("customer tidak ditemukan")
print(run_agent(customer["id"], sys.argv[2]))
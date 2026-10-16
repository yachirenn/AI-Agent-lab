"""Pemakaian: python -m scripts.check_roles
Membuktikan role MCP tidak bisa menulis atau membaca tabel sensitif."""
import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()
CHECKS = [
    ("UPDATE cs_tickets", "UPDATE cs_tickets SET status = 'resolved' WHERE false"),
    ("DELETE customers", "DELETE FROM customers WHERE false"),
    ("INSERT outbox", "INSERT INTO outbox (kind, channel, recipient, body) SELECT 'notification','telegram','x','x' WHERE false"),
    ("SELECT outbox", "SELECT 1 FROM outbox LIMIT 1"),
    ("SELECT conversations", "SELECT 1 FROM conversations LIMIT 1"),
    ("SELECT customer_identities", "SELECT 1 FROM customer_identities LIMIT 1"),
]

bad = False
with psycopg.connect(os.environ["MCP_DATABASE_URL"], autocommit=True) as conn:
    print("login sebagai:", conn.execute("SELECT current_user").fetchone()[0])
    conn.execute("SELECT 1 FROM cs_tickets LIMIT 1")           # sanity: yang seharusnya boleh
    for label, sql in CHECKS:
        try:
            conn.execute(sql)
        except psycopg.Error as exc:
            print(f"OK       ditolak: {label} ({type(exc).__name__})")
        else:
            bad = True
            print(f"BAHAYA   DIIZINKAN: {label}")
sys.exit(1 if bad else 0)
"""Pemakaian: python -m scripts.rotate_passwords
Membuat password acak untuk role enerva, enerva_ro, enerva_staff. Tidak mencetak rahasia."""
import getpass
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
from dotenv import dotenv_values
from psycopg import sql

ENV = Path(".env")
ROLES = {"enerva": "DATABASE_URL", "enerva_staff": "MCP_DATABASE_URL"}   # enerva_ro tidak disimpan di .env


def with_password(url: str, user: str, password: str) -> str:
    p = urlsplit(url)
    port = f":{p.port}" if p.port else ""
    return urlunsplit(p._replace(netloc=f"{user}:{password}@{p.hostname}{port}"))


env = dotenv_values(ENV)
if not all(env.get(v) for v in ROLES.values()):
    sys.exit("DATABASE_URL / MCP_DATABASE_URL tidak ditemukan di .env")

new = {r: secrets.token_hex(16) for r in ("enerva", "enerva_ro", "enerva_staff")}
admin_pw = os.environ.get("PGPASSWORD") or getpass.getpass("Password user postgres (kosongkan bila tidak ada): ")

with psycopg.connect(host="localhost", user="postgres", password=admin_pw or None, dbname="postgres", autocommit=True) as c:
    for role, pw in new.items():
        c.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(role), sql.Literal(pw)))

text = ENV.read_text(encoding="utf-8")
for role, var in ROLES.items():
    line = f"{var}={with_password(env[var], role, new[role])}"
    text = re.sub(rf"^{var}=.*$", lambda _: line, text, flags=re.M)
tmp = ENV.with_suffix(".tmp")
tmp.write_text(text, encoding="utf-8")
tmp.replace(ENV)
print("Password 3 role diganti dan .env diperbarui.")

# Apakah server benar-benar memeriksa password?
host = urlsplit(env["DATABASE_URL"])
try:
    psycopg.connect(host=host.hostname, port=host.port or 5432, user="enerva_staff",
                    password="password-yang-pasti-salah", dbname=host.path.lstrip("/"), connect_timeout=5).close()
except psycopg.OperationalError:
    print("OK: password salah ditolak server.")
else:
    print("PERINGATAN: server MENERIMA password salah. pg_hba.conf memakai 'trust'. Lihat langkah 2.")
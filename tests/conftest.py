import os

from psycopg import sql
import pytest
from dotenv import load_dotenv

load_dotenv()
# Harus dijalankan sebelum app.db.repo diimpor, supaya pool memakai DB tes.
os.environ["DATABASE_URL"] = os.environ["DATABASE_URL"].rsplit("/", 1)[0] + "/enerva_test"
os.environ["PREFERENCES_LEARNING"] = "off"

os.environ["MCP_DATABASE_URL"] = os.environ["DATABASE_URL"]   # tes MCP memakai DB tes, bukan DB dev
os.environ["ENERVA_ALLOW_OWNER"] = "1"                        # hanya berlaku di database berakhiran _test

from app.db import repo  # noqa: E402

KEEP = {"stations"}      # data seed yang dibutuhkan tes, tidak ikut dihapus


def _truncate_all() -> None:
    assert os.environ["DATABASE_URL"].endswith("_test"), "menolak TRUNCATE di database non-tes"
    with repo.tx() as conn:
        names = [
            r["tablename"]
            for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
            if r["tablename"] not in KEEP
        ]
        if names:
            conn.execute(
                sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                    sql.SQL(", ").join(sql.Identifier(n) for n in names)
                )
            )


@pytest.fixture(autouse=True)
def clean_db():
    _truncate_all()      # bersih sebelum tes: sisa run yang rusak tidak mengganggu
    yield
    _truncate_all()
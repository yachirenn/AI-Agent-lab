import argparse
import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

from app.db import repo  # noqa: E402
from app.logging_config import setup_logging  # noqa: E402

setup_logging()
log = logging.getLogger("inbox-recovery")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pulihkan satu Inbox dead yang hasilnya sudah tersimpan."
    )
    parser.add_argument(
        "inbox_id",
        type=int,
        help="ID Inbox yang akan dipulihkan",
    )
    args = parser.parse_args()

    if args.inbox_id < 1:
        parser.error("inbox_id harus lebih besar dari 0")

    database_url = os.environ.get("DATABASE_URL", "")
    allowed_database = os.environ.get("RECOVERY_ALLOWED_DATABASE", "")

    database_name = urlparse(database_url).path.rstrip("/").split("/")[-1]

    if not database_name or not allowed_database:
        parser.error(
            "Recovery ditolak: DATABASE_URL dan RECOVERY_ALLOWED_DATABASE "
            "harus tersedia."
        )

    if not allowed_database.endswith("_test"):
        parser.error(
            "Recovery ditolak: RECOVERY_ALLOWED_DATABASE "
            "harus menunjuk database dengan akhiran '_test'."
        )

    if database_name != allowed_database:
        parser.error(
            f"Recovery ditolak: database '{database_name}' tidak cocok "
            "dengan RECOVERY_ALLOWED_DATABASE."
        )

    repo.get_pool()
    try:
        recovered = repo.recover_dead_inbox_result(args.inbox_id)

        if recovered:
            log.info(
                "Inbox %s berhasil dipulihkan dan difinalisasi.",
                args.inbox_id,
            )
            return 0

        log.warning(
            "Inbox %s tidak dipulihkan. Pastikan statusnya dead "
            "dan result_ready bernilai TRUE.",
            args.inbox_id,
        )
        return 1
    except Exception:
        log.exception("Pemulihan Inbox %s gagal.", args.inbox_id)
        return 2
    finally:
        repo.close_pool()


if __name__ == "__main__":
    raise SystemExit(main())

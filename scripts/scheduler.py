import logging

from dotenv import load_dotenv

load_dotenv()
from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402

from app.logging_config import setup_logging  # noqa: E402
from app.services import inactivity  # noqa: E402

setup_logging()
log = logging.getLogger("scheduler")


def job() -> None:
    try:
        inactivity.run_once()
    except Exception:
        log.exception("job inaktivitas gagal")   # exception tidak boleh mematikan scheduler


sched = BlockingScheduler(timezone="Asia/Jakarta")
sched.add_job(
    job, CronTrigger(hour=10, minute=0), id="inactivity",
    max_instances=1, coalesce=True, misfire_grace_time=3600,
)
log.info("scheduler aktif: inaktivitas setiap hari 10:00 WIB (Ctrl+C untuk berhenti)")
sched.start()

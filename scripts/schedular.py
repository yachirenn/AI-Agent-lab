import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.services import inactivity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
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
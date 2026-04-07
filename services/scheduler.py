from apscheduler.schedulers.background import BackgroundScheduler

from config import DAILY_REPORT_HOUR
from db.database import SessionLocal
from services.notifications import send_daily_summary

scheduler = None


def start_scheduler():
    global scheduler
    if scheduler:
        return scheduler
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    def _job():
        db = SessionLocal()
        try:
            send_daily_summary(db)
        finally:
            db.close()

    scheduler.add_job(_job, "cron", hour=DAILY_REPORT_HOUR, minute=0, id="daily_summary", replace_existing=True)
    scheduler.start()
    return scheduler

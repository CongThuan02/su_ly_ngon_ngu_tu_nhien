"""
scheduler.py — APScheduler với SQLAlchemy job store (jobs sống sót qua restart).
Hỗ trợ cả DateTrigger (một lần) và CronTrigger (hàng ngày / hàng tuần).
"""

import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger

import firebase_client
from database import SessionLocal, Reminder

logger  = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "reminders.db")

scheduler = BackgroundScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")},
    timezone="Asia/Ho_Chi_Minh",
)


# ── Job function ──────────────────────────────────────────────────────────────

def _fire_reminder(reminder_id: int, fcm_token: str, task: str, time_text: str, location: str, recur: str):
    title = "Nhắc nhở"
    parts = []
    if task:
        parts.append(task)
    if time_text:
        parts.append(f"lúc {time_text}")
    if location:
        parts.append(f"tại {location}")
    body = " ".join(parts) if parts else "Bạn có một sự kiện sắp diễn ra."

    success = firebase_client.send_notification(fcm_token, title, body)

    # Cập nhật DB — với recurring chỉ cập nhật lần cuối chạy, không đổi status
    db = SessionLocal()
    try:
        reminder = db.get(Reminder, reminder_id)
        if reminder:
            if recur == "none":
                reminder.status = "sent" if success else "failed"
            # Với recurring: giữ status "pending", chỉ log
            db.commit()
    finally:
        db.close()

    if not success:
        logger.error(f"FCM thất bại cho reminder #{reminder_id}")


# ── API công khai ─────────────────────────────────────────────────────────────

def schedule_reminder(
    reminder_id: int,
    fcm_token:   str,
    task:        str,
    time_text:   str,
    location:    str,
    recur:       str,
    # Dùng cho recur="none"
    fire_at:     datetime | None = None,
    # Dùng cho recur="daily" / "weekly"
    hour:        int | None = None,
    minute:      int = 0,
    dow:         int | None = None,    # 0=Mon…6=Sun
) -> str:
    """
    Đặt lịch một lần hoặc định kỳ. Trả về job_id.
    """
    job_kwargs = {
        "reminder_id": reminder_id,
        "fcm_token":   fcm_token,
        "task":        task,
        "time_text":   time_text,
        "location":    location,
        "recur":       recur,
    }
    job_id = f"reminder_{reminder_id}"

    if recur == "none":
        trigger = DateTrigger(run_date=fire_at, timezone="Asia/Ho_Chi_Minh")

    elif recur == "daily":
        trigger = CronTrigger(hour=hour, minute=minute, timezone="Asia/Ho_Chi_Minh")

    elif recur == "weekly":
        # APScheduler dùng 0=Mon…6=Sun, CronTrigger dùng 'mon','tue',...
        _dow_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        dow_name   = _dow_names[dow] if dow is not None else _dow_names[0]
        trigger    = CronTrigger(day_of_week=dow_name, hour=hour, minute=minute,
                                 timezone="Asia/Ho_Chi_Minh")
    else:
        raise ValueError(f"recur không hợp lệ: '{recur}'")

    job = scheduler.add_job(
        _fire_reminder,
        trigger=trigger,
        kwargs=job_kwargs,
        id=job_id,
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info(f"Job '{job.id}' đã đặt (recur={recur}) cho reminder #{reminder_id}")
    return job.id


def cancel_reminder(job_id: str) -> bool:
    try:
        scheduler.remove_job(job_id)
        return True
    except Exception:
        return False

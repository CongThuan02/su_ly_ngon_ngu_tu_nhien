"""
database.py — SQLAlchemy model và session factory.
"""

import json
import os
from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

DB_PATH      = os.getenv("DB_PATH", "reminders.db")
engine       = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


class Reminder(Base):
    __tablename__ = "reminders"

    id           = Column(Integer,  primary_key=True, autoincrement=True)
    raw_text     = Column(Text,     nullable=False)
    fcm_token    = Column(Text,     nullable=False)
    task         = Column(Text)
    time_text    = Column(Text)                        # chuỗi TIME thô từ NER / người dùng
    location     = Column(Text)
    partner      = Column(Text)                        # JSON list '["thầy lộc"]'
    # Thời điểm kích hoạt (chỉ có giá trị khi recur="none")
    fire_at      = Column(DateTime)
    # Lặp lại
    recur        = Column(String(16), nullable=False, default="none")
    # "none" | "daily" | "weekly"
    recur_hour   = Column(Integer)                     # giờ cron (0-23)
    recur_minute = Column(Integer,  default=0)         # phút cron (0-59)
    recur_dow    = Column(Integer)                     # 0=Mon…6=Sun, chỉ khi weekly
    # Metadata
    job_id       = Column(String(64))
    status       = Column(String(16), nullable=False, default="pending")
    # "pending" | "sent" | "failed" | "cancelled"
    created_at   = Column(DateTime, nullable=False, default=datetime.now)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def partner_list(self) -> list[str]:
        if not self.partner:
            return []
        try:
            return json.loads(self.partner)
        except (ValueError, TypeError):
            return [self.partner]

    def to_dict(self) -> dict:
        d = {
            "id":         self.id,
            "raw_text":   self.raw_text,
            "task":       self.task,
            "time_text":  self.time_text,
            "location":   self.location,
            "partner":    self.partner_list(),
            "recur":      self.recur,
            "status":     self.status,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
        }
        if self.recur == "none":
            d["fire_at"] = self.fire_at.strftime("%Y-%m-%d %H:%M") if self.fire_at else None
        else:
            # Hiển thị lịch lặp lại
            time_label = f"{self.recur_hour:02d}:{self.recur_minute:02d}"
            if self.recur == "daily":
                d["schedule"] = f"Hàng ngày lúc {time_label}"
            elif self.recur == "weekly" and self.recur_dow is not None:
                days = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
                d["schedule"] = f"Hàng tuần vào {days[self.recur_dow]} lúc {time_label}"
            else:
                d["schedule"] = f"Hàng tuần lúc {time_label}"
        return d


def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency — tự động đóng session sau mỗi request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

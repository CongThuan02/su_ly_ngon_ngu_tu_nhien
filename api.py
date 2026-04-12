"""
api.py — Vietnamese NER API với tính năng đặt lịch nhắc nhở + Firebase push notification.

Chạy:
    uvicorn api:app --host 0.0.0.0 --port 8000

Biến môi trường:
    MODEL_DIR                   đường dẫn thư mục model (mặc định: model_output)
    DB_PATH                     đường dẫn file SQLite (mặc định: reminders.db)
    FIREBASE_CREDENTIALS_JSON   đường dẫn file service account Firebase
"""

import json
import os
import logging
from contextlib import asynccontextmanager

import torch
from transformers import AutoTokenizer, AutoModelForTokenClassification
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

import database
import time_parser
import scheduler as sched
from preprocessor import preprocess

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Cấu hình model ────────────────────────────────────────────────────────────
MODEL_DIR = os.getenv("MODEL_DIR", "model_output")
MAX_LEN   = 128

LABELS   = ["O", "B-TIME", "I-TIME", "B-TASK", "I-TASK", "B-LOCATION", "I-LOCATION", "B-PARTNER", "I-PARTNER"]
LABEL2ID = {l: i for i, l in enumerate(LABELS)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}

# ── Tải model ─────────────────────────────────────────────────────────────────
if not os.path.isdir(MODEL_DIR):
    raise FileNotFoundError(
        f"Không tìm thấy thư mục model '{MODEL_DIR}'. "
        "Hãy chạy notebook để train và lưu model trước."
    )

logger.info(f"Đang tải model từ '{MODEL_DIR}'...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, use_fast=False)
model     = AutoModelForTokenClassification.from_pretrained(MODEL_DIR)
model.eval()
logger.info("Model sẵn sàng.")

# ── Inference ─────────────────────────────────────────────────────────────────
def _get_word_ids(tokens: list[str], n: int) -> list:
    """
    Tính word_ids thủ công cho non-fast tokenizer (PhoBERT / SentencePiece).
    n = số vị trí cần trả về (bằng độ dài logits).
    """
    word_ids = [None]  # [CLS]
    for word_idx, word in enumerate(tokens):
        sub = tokenizer.tokenize(word) or [tokenizer.unk_token]
        word_ids.extend([word_idx] * len(sub))
        if len(word_ids) >= n - 1:
            break
    word_ids.append(None)  # [SEP]
    word_ids += [None] * (n - len(word_ids))
    return word_ids[:n]


def predict(text: str) -> dict:
    """Nhận văn bản đã chuẩn hoá, trả về entities."""
    tokens = text.split()
    enc = tokenizer(
        tokens,
        is_split_into_words=True,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_LEN,
    )
    with torch.no_grad():
        outputs = model(**enc)

    preds    = torch.argmax(outputs.logits[0], dim=-1).tolist()
    word_ids = _get_word_ids(tokens, len(preds))

    word_preds, prev = [], None
    for pid, wid in zip(preds, word_ids):
        if wid is None or wid == prev:
            prev = wid
            continue
        word_preds.append((tokens[wid], ID2LABEL[pid]))
        prev = wid

    raw_entities, current = [], None
    for word, label in word_preds:
        if label.startswith("B-"):
            if current:
                raw_entities.append(current)
            current = {"text": word, "label": label[2:]}
        elif label.startswith("I-") and current:
            current["text"] += " " + word
        else:
            if current:
                raw_entities.append(current)
            current = None
    if current:
        raw_entities.append(current)

    entities_dict: dict = {}
    for ent in raw_entities:
        lbl = ent["label"]
        if lbl == "PARTNER":
            entities_dict.setdefault("PARTNER", []).append(ent["text"])
        else:
            if lbl not in entities_dict:
                entities_dict[lbl] = ent["text"]

    return {"text": text, "entities": [entities_dict]}


def predict_raw(raw_text: str) -> dict:
    """Tiền xử lý → NER. Trả về cả original và preprocessed text."""
    cleaned = preprocess(raw_text)
    result  = predict(cleaned)
    result["original_text"]     = raw_text
    result["preprocessed_text"] = cleaned
    return result


# ── FastAPI lifecycle ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    database.create_tables()
    sched.scheduler.start()
    logger.info("Scheduler đã khởi động.")
    yield
    sched.scheduler.shutdown(wait=False)
    logger.info("Scheduler đã dừng.")

app = FastAPI(
    title="Vietnamese NER + Reminder API",
    description=(
        "Nhận diện thực thể (TIME, TASK, LOCATION, PARTNER) trong văn bản tiếng Việt, "
        "lưu lịch nhắc nhở vào database và gửi Firebase push notification đúng giờ."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class PredictRequest(BaseModel):
    text: str


class RemindRequest(BaseModel):
    text: str
    fcm_token: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "NER + Reminder API đang chạy", "version": "2.0.0"}


@app.post("/predict")
def api_predict(body: PredictRequest):
    """Trích xuất thực thể từ văn bản (không lưu DB, không đặt lịch)."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Trường 'text' không được rỗng.")
    return predict_raw(body.text)


@app.post("/remind", status_code=201)
def api_remind(body: RemindRequest, db: Session = Depends(database.get_db)):
    """
    Trích xuất thực thể → lưu lịch nhắc nhở → đặt lịch Firebase push notification.

    Hỗ trợ:
      - Một thời gian:  "20h họp dự án ở phòng họp tầng 3"
      - Nhiều thời gian: "nhắc uống thuốc vào 12 giờ và 20 giờ hàng ngày"
      - Lặp lại:        "hàng ngày", "mỗi ngày", "mỗi thứ 2"

    Response:
      Danh sách các reminder đã tạo (một reminder cho mỗi giờ tìm thấy).
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Trường 'text' không được rỗng.")
    if not body.fcm_token.strip():
        raise HTTPException(status_code=400, detail="Trường 'fcm_token' không được rỗng.")

    from datetime import datetime as dt_cls

    # 1. Tiền xử lý + NER — lấy TASK, LOCATION, PARTNER
    result   = predict_raw(body.text)
    cleaned  = result["preprocessed_text"]
    entities = result["entities"][0]
    task     = entities.get("TASK")
    location = entities.get("LOCATION")
    partners = entities.get("PARTNER", [])

    # 2. Parse tất cả thời gian + kiểu lặp từ văn bản đã chuẩn hoá
    try:
        parsed_times = time_parser.parse_all(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not parsed_times:
        raise HTTPException(
            status_code=422,
            detail="Không tìm thấy thông tin thời gian trong câu.",
        )

    # 3. Tạo một Reminder cho mỗi thời gian tìm thấy
    created = []
    for pt in parsed_times:
        # Kiểm tra quá khứ (chỉ áp dụng cho lịch một lần)
        if pt.recur == "none" and pt.fire_at and pt.fire_at < dt_cls.now():
            continue  # bỏ qua giờ đã qua, không báo lỗi

        time_label = f"{pt.hour:02d}h{pt.minute:02d}" if pt.minute else f"{pt.hour}h"

        reminder = database.Reminder(
            raw_text     = body.text,
            fcm_token    = body.fcm_token,
            task         = task,
            time_text    = time_label,
            location     = location,
            partner      = json.dumps(partners, ensure_ascii=False),
            fire_at      = pt.fire_at,          # None nếu recurring
            recur        = pt.recur,
            recur_hour   = pt.hour,
            recur_minute = pt.minute,
            recur_dow    = pt.dow,
            status       = "pending",
        )
        db.add(reminder)
        db.commit()
        db.refresh(reminder)

        # 4. Đặt lịch APScheduler
        job_id = sched.schedule_reminder(
            reminder_id = reminder.id,
            fcm_token   = body.fcm_token,
            task        = task or "",
            time_text   = time_label,
            location    = location or "",
            recur       = pt.recur,
            fire_at     = pt.fire_at,
            hour        = pt.hour,
            minute      = pt.minute,
            dow         = pt.dow,
        )
        reminder.job_id = job_id
        db.commit()
        created.append(reminder.to_dict())

    if not created:
        raise HTTPException(
            status_code=422,
            detail="Tất cả thời gian trong câu đã qua. Vui lòng nhập thời gian trong tương lai.",
        )

    # Tạo thông báo tóm tắt
    def _summary(r: dict) -> str:
        if r["recur"] == "daily":
            return r["schedule"]
        if r["recur"] == "weekly":
            return r["schedule"]
        return f"lúc {r['fire_at']}"

    summaries = " và ".join(_summary(r) for r in created)
    return {
        "message":   f"Đã tạo {len(created)} lịch nhắc nhở: {summaries}.",
        "reminders": created,
    }


@app.get("/reminders")
def list_reminders(db: Session = Depends(database.get_db)):
    """Lấy danh sách tất cả lịch nhắc nhở."""
    reminders = (
        db.query(database.Reminder)
        .order_by(database.Reminder.recur_hour, database.Reminder.fire_at)
        .all()
    )
    return {"reminders": [r.to_dict() for r in reminders]}


@app.get("/reminders/{reminder_id}")
def get_reminder(reminder_id: int, db: Session = Depends(database.get_db)):
    """Lấy chi tiết một lịch nhắc nhở."""
    reminder = db.get(database.Reminder, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Không tìm thấy reminder.")
    return reminder.to_dict()


@app.delete("/reminders/{reminder_id}", status_code=200)
def delete_reminder(reminder_id: int, db: Session = Depends(database.get_db)):
    """Huỷ và xoá một lịch nhắc nhở."""
    reminder = db.get(database.Reminder, reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Không tìm thấy reminder.")

    if reminder.job_id:
        sched.cancel_reminder(reminder.job_id)

    reminder.status = "cancelled"
    db.commit()
    db.delete(reminder)
    db.commit()
    return {"message": f"Đã huỷ lịch nhắc nhở #{reminder_id}."}


# ── Chạy trực tiếp ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)

"""
time_parser.py — Chuyển chuỗi thời gian tiếng Việt thành datetime (UTC+7 local).

Hỗ trợ:
  "20h"                      → hôm nay 20:00
  "20h30"                    → hôm nay 20:30
  "12 giờ và 20 giờ"         → [hôm nay 12:00, hôm nay 20:00]
  "sáng mai lúc 9h"          → ngày mai 09:00
  "thứ 4 lúc 14h"            → thứ Tư gần nhất 14:00
  "ngày 25/12 lúc 9h"        → 25/12 năm nay 09:00
  "hàng ngày lúc 8h"         → daily cron (recurrence)
  "mỗi thứ 2 lúc 9h"        → weekly cron mỗi thứ Hai
"""

import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field

# ── Bảng thay thế từ khoá ────────────────────────────────────────────────────

_REPLACEMENTS = [
    # "tuần sau/tới" → sentinel trước khi thứ bị replace
    (r"tuần sau|tuần tới|tuần toi|tuan sau|tuan toi", "_nextweek_"),
    # Buổi
    (r"buổi sáng|sáng nay|sáng mai|sáng",   "_sang_"),
    (r"buổi trưa|trưa nay|trưa",             "_trua_"),
    (r"buổi chiều|chiều nay|chiều mai|chiều", "_chieu_"),
    (r"buổi tối|tối nay|tối mai|tối",         "_toi_"),
    # Ngày
    (r"ngày kia|kia",   "_dayafter_"),
    (r"ngày mai|mai",   "_tomorrow_"),
    (r"hôm nay",        "_today_"),
    # Thứ
    (r"thứ hai|t2",     "_mon_"),
    (r"thứ ba|t3",      "_tue_"),
    (r"thứ tư|t4",      "_wed_"),
    (r"thứ năm|t5",     "_thu_"),
    (r"thứ sáu|t6",     "_fri_"),
    (r"thứ bảy|t7",     "_sat_"),
    (r"chủ nhật|cn",    "_sun_"),
    # Đơn vị giờ — phải trước "lúc|vào"
    (r"giờ",  "h"),
    (r"phút", "m"),
    # Định dạng "HH:MM" → "HHhMM"  (ví dụ: "20:00" → "20h00")
    (r"(\d{1,2}):(\d{2})", r"\1h\2"),
    # Giới từ thời gian
    (r"lúc|vào",  " "),
]

_WEEKDAY_MAP = {
    "_mon_": 0, "_tue_": 1, "_wed_": 2, "_thu_": 3,
    "_fri_": 4, "_sat_": 5, "_sun_": 6,
}

# Từ khoá lặp lại
_DAILY_RE   = re.compile(r"hàng\s*ngày|mỗi\s*ngày|hằng\s*ngày|daily")
_WEEKLY_RE  = re.compile(r"hàng\s*tuần|mỗi\s*tuần|weekly")
# Cụm "mỗi thứ N" → weekly vào thứ cụ thể (xử lý riêng)
_EACH_DOW_RE = re.compile(
    r"mỗi\s*(thứ hai|t2|thứ ba|t3|thứ tư|t4|thứ năm|t5|thứ sáu|t6|thứ bảy|t7|chủ nhật|cn)"
)

# ── Dataclass kết quả ────────────────────────────────────────────────────────

@dataclass
class ParsedTime:
    hour:       int
    minute:     int = 0
    # Recurrence
    recur:      str = "none"   # "none" | "daily" | "weekly"
    dow:        int | None = None  # 0=Mon … 6=Sun, chỉ khi recur="weekly"
    # Thời điểm kích hoạt lần đầu (chỉ khi recur="none")
    fire_at:    datetime | None = None


# ── Hàm nội bộ ───────────────────────────────────────────────────────────────

def _normalise(raw: str) -> str:
    s = raw.lower().strip()
    for pattern, replacement in _REPLACEMENTS:
        s = re.sub(pattern, replacement, s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Giờ mặc định khi chỉ có buổi, không có giờ cụ thể
_SESSION_DEFAULT_HOUR = {
    "_sang_":  8,
    "_trua_":  12,
    "_chieu_": 14,
    "_toi_":   19,
}


def _apply_session(hour: int, session: str) -> int:
    if session == "_sang_":
        return hour
    if session == "_trua_":
        return 12
    if session == "_chieu_":
        return hour if hour >= 12 else hour + 12
    if session == "_toi_":
        return hour if hour >= 18 else hour + 12
    return hour


def _hm(h_str: str, m_str: str) -> tuple[int, int]:
    return int(h_str), (int(m_str) if m_str else 0)


def _next_weekday(now: datetime, target_dow: int, force_next_week: bool = False) -> datetime:
    days = (target_dow - now.weekday()) % 7
    if days == 0 or force_next_week:
        days += 7   # "tuần sau" hoặc đúng hôm nay → tuần tiếp theo
    return now + timedelta(days=days)


# ── Trích xuất tất cả giờ trong văn bản gốc ─────────────────────────────────

# Regex khớp: "12h", "12h30", "12 giờ", "12 giờ 30", "12:30", "20:00"
_TIME_PATTERN = re.compile(
    r"\b(\d{1,2})\s*(?:h|giờ|g)\s*(\d{0,2})\b"   # 20h, 20h30, 20 giờ
    r"|"
    r"\b(\d{1,2}):(\d{2})\b",                      # 20:00, 9:30
    re.IGNORECASE,
)


def extract_raw_times(text: str) -> list[str]:
    """
    Tìm tất cả cụm thời gian trong văn bản gốc.
    Hỗ trợ: "12 giờ", "20h", "20h30", "20:00", "9:30",
            "tối thứ 3", "sáng thứ 2 tuần sau", v.v.
    """
    results = []

    # A. Giờ số cụ thể
    for m in _TIME_PATTERN.finditer(text):
        results.append(m.group(0).strip())

    # B. Nếu không tìm thấy giờ số → tìm cụm buổi [+ thứ] [+ tuần sau]
    if not results:
        session_pat = (
            r"(buổi\s*)?(sáng|trưa|chiều|tối)"
            r"(\s+(thứ\s*(hai|ba|tư|năm|sáu|bảy)|chủ\s*nhật|t[2-7]|cn))?"
            r"(\s+(tuần\s*sau|tuần\s*tới|tuan\s*sau|tuan\s*toi))?"
        )
        m = re.search(session_pat, text, re.IGNORECASE)
        if m:
            results.append(m.group(0).strip())

    return results


def parse_recurrence(text: str) -> tuple[str, int | None]:
    """
    Phát hiện kiểu lặp lại trong văn bản.
    Trả về (recur_type, dow):
      ("none",   None)     — không lặp
      ("daily",  None)     — hàng ngày
      ("weekly", 0..6)     — hàng tuần vào thứ cụ thể
    """
    low = text.lower()

    # "mỗi thứ N" → weekly + dow
    m = _EACH_DOW_RE.search(low)
    if m:
        dow_str = m.group(1)
        mapping = {
            "thứ hai": 0, "t2": 0,
            "thứ ba": 1,  "t3": 1,
            "thứ tư": 2,  "t4": 2,
            "thứ năm": 3, "t5": 3,
            "thứ sáu": 4, "t6": 4,
            "thứ bảy": 5, "t7": 5,
            "chủ nhật": 6, "cn": 6,
        }
        dow = mapping.get(dow_str)
        return ("weekly", dow)

    if _DAILY_RE.search(low):
        return ("daily", None)

    if _WEEKLY_RE.search(low):
        return ("weekly", None)  # tuần, không biết thứ mấy → dùng thứ hiện tại

    return ("none", None)


# ── Parse một chuỗi thời gian đơn → ParsedTime ───────────────────────────────

def parse(time_str: str, now: datetime | None = None,
          recur: str = "none", dow: int | None = None) -> ParsedTime:
    """
    Phân tích một cụm thời gian và trả về ParsedTime.
    - recur / dow được truyền vào từ parse_recurrence().
    - Khi recur != "none", fire_at = None (APScheduler dùng CronTrigger).
    - Khi recur == "none", fire_at = datetime lần kích hoạt đầu tiên.
    """
    if now is None:
        now = datetime.now()

    s = _normalise(time_str)

    # Xác định buổi và tuần sau
    session_m  = re.search(r"_(sang|trua|chieu|toi)_", s)
    session    = f"_{session_m.group(1)}_" if session_m else ""
    next_week  = "_nextweek_" in s

    h, mn = None, 0  # sẽ được gán bên dưới

    # ── P1: ngày/tháng[/năm] Hh[M] ───────────────────────────────────────────
    m = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s*(\d{1,2})hm?\s*(\d{0,2})", s)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        h, mn = _hm(m.group(4), m.group(5))
        dt = datetime(year, month, day, h, mn)
        if dt < now:
            dt = dt.replace(year=dt.year + 1)
        return ParsedTime(hour=h, minute=mn, recur="none", fire_at=dt)

    # ── P2: ngày mai ──────────────────────────────────────────────────────────
    if "_tomorrow_" in s:
        m = re.search(r"(\d{1,2})h\s*(\d{0,2})", s)
        if m:
            h, mn = _hm(m.group(1), m.group(2))
            h = _apply_session(h, session)
            base = now + timedelta(days=1)
            dt = datetime(base.year, base.month, base.day, h, mn)
            return ParsedTime(hour=h, minute=mn, recur="none", fire_at=dt)

    # ── P3: hôm nay ───────────────────────────────────────────────────────────
    if "_today_" in s:
        m = re.search(r"(\d{1,2})h\s*(\d{0,2})", s)
        if m:
            h, mn = _hm(m.group(1), m.group(2))
            dt = datetime(now.year, now.month, now.day, h, mn)
            return ParsedTime(hour=h, minute=mn, recur="none", fire_at=dt)

    # ── P4: ngày kia ──────────────────────────────────────────────────────────
    if "_dayafter_" in s:
        m = re.search(r"(\d{1,2})h\s*(\d{0,2})", s)
        if m:
            h, mn = _hm(m.group(1), m.group(2))
            base = now + timedelta(days=2)
            dt = datetime(base.year, base.month, base.day, h, mn)
            return ParsedTime(hour=h, minute=mn, recur="none", fire_at=dt)

    # ── P5: thứ N cụ thể (có hoặc không có giờ) ──────────────────────────────
    for sentinel, wdow in _WEEKDAY_MAP.items():
        if sentinel in s:
            m = re.search(r"(\d{1,2})h\s*(\d{0,2})", s)
            if m:
                h, mn = _hm(m.group(1), m.group(2))
                h = _apply_session(h, session)
            elif session:
                # Chỉ có buổi, không có giờ → dùng giờ mặc định
                h  = _SESSION_DEFAULT_HOUR[session]
                mn = 0
            else:
                continue  # không đủ thông tin giờ

            if recur == "weekly":
                return ParsedTime(hour=h, minute=mn, recur="weekly", dow=wdow)
            base = _next_weekday(now, wdow, force_next_week=next_week)
            dt   = datetime(base.year, base.month, base.day, h, mn)
            return ParsedTime(hour=h, minute=mn, recur="none", fire_at=dt)

    # ── P6: chỉ có buổi, không có thứ/giờ cụ thể → hôm nay + giờ mặc định ──
    if session and not re.search(r"(\d{1,2})h\s*(\d{0,2})", s):
        h  = _SESSION_DEFAULT_HOUR[session]
        mn = 0
        base = now + timedelta(days=(1 if next_week else 0))
        dt   = datetime(base.year, base.month, base.day, h, mn)
        return ParsedTime(hour=h, minute=mn, recur=recur, fire_at=dt if recur == "none" else None)

    # ── P8: Hh[M] đơn thuần ──────────────────────────────────────────────────
    m = re.search(r"(\d{1,2})h\s*(\d{0,2})", s)
    if m:
        h, mn = _hm(m.group(1), m.group(2))
        h = _apply_session(h, session)

        if recur == "daily":
            return ParsedTime(hour=h, minute=mn, recur="daily")

        if recur == "weekly":
            used_dow = dow if dow is not None else now.weekday()
            return ParsedTime(hour=h, minute=mn, recur="weekly", dow=used_dow)

        # Một lần: hôm nay
        dt = datetime(now.year, now.month, now.day, h, mn)
        return ParsedTime(hour=h, minute=mn, recur="none", fire_at=dt)

    raise ValueError(f"Không thể phân tích thời gian: '{time_str}'")


def parse_all(text: str, now: datetime | None = None) -> list[ParsedTime]:
    """
    Hàm chính — nhận văn bản thô, trả về danh sách ParsedTime
    (một phần tử cho mỗi giờ tìm thấy).

    VD: "nhắc uống thuốc vào 12 giờ và 20 giờ hàng ngày"
        → [ParsedTime(hour=12, recur='daily'),
           ParsedTime(hour=20, recur='daily')]
    """
    if now is None:
        now = datetime.now()

    recur, dow = parse_recurrence(text)
    raw_times  = extract_raw_times(text)

    if not raw_times:
        raise ValueError("Không tìm thấy thông tin giờ trong câu.")

    results = []
    for rt in raw_times:
        try:
            pt = parse(rt, now=now, recur=recur, dow=dow)
            results.append(pt)
        except ValueError:
            continue

    if not results:
        raise ValueError(f"Không thể phân tích thời gian từ: '{text}'")

    return results

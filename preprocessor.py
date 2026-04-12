"""
preprocessor.py — Chuẩn hoá văn bản tiếng Việt không chính thống trước khi đưa vào NER.

Xử lý:
  "Nhớ nhé, 20h họp dự án đó"  → "20h họp dự án"
  "20:00 họp DA @ tầng 3 (phòng họp)" → "20:00 họp dự án tại tầng 3 phòng họp"
  "@" → "tại", "(nội dung)" → "nội dung", "DA" → "dự án"
"""

import re

# ── 1. Cụm mở đầu cảm thán / khẩu ngữ (xoá khỏi đầu câu) ───────────────────
# Khớp cả có dấu phẩy hoặc không, ở đầu câu
_FILLER_PREFIX = re.compile(
    r"^("
    r"nhớ nhé[,!.]*|nhớ nha[,!.]*|nhớ nghe[,!.]*"
    r"|nhé[,!.]*|nha[,!.]*|nghe[,!.]*"
    r"|ơi[,!.]*|này[,!.]*|này nhé[,!.]*|này nha[,!.]*"
    r"|hôm nay nhé[,!.]*|hey[,!.]*|ê[,!.]*"
    r"|bạn ơi[,!.]*|anh ơi[,!.]*|chị ơi[,!.]*|em ơi[,!.]*"
    r"|lưu ý[,!.:]*|chú ý[,!.:]*|quan trọng[,!.:]*"
    r"|remind[,!.:]*|note[,!.:]*|fyi[,!.:]*"
    r")\s*",
    re.IGNORECASE,
)

# ── 2. Từ đuôi khẩu ngữ (xoá khỏi cuối câu) ─────────────────────────────────
_FILLER_SUFFIX = re.compile(
    r"\s*("
    r"đó nhé|đó nha|đó nghe|đó nhen"
    r"|nhé|nha|nghe|nhen|đó|nhe"
    r"|nhớ nhé|nhớ nha|nhớ nghe"
    r"|ok chưa|ok không|oke|ok"
    r"|đấy nhé|đấy nha|đấy"
    # Đuôi câu hỏi kiểm tra: "xem có ... không", "xem thử", "thử xem"
    r"|xem có\s+\S+\s+không|xem có không|xem thử|thử xem|xem sao"
    r"|có bị\s+\S+\s+không|có ổn không|có được không"
    r")[!.?]*$",
    re.IGNORECASE,
)

# ── 3. Bảng viết tắt ──────────────────────────────────────────────────────────
# Thứ tự quan trọng — dài trước để tránh match lồng nhau
ABBREVIATIONS: list[tuple[str, str]] = [
    # Công việc
    ("DUAN",  "dự án"),
    ("DA",    "dự án"),
    ("HP",    "họp"),
    ("BC",    "báo cáo"),
    ("TD",    "tiến độ"),
    ("KH",    "kế hoạch"),
    ("HD",    "hợp đồng"),
    ("TT",    "thuyết trình"),
    ("PV",    "phỏng vấn"),
    ("DT",    "đào tạo"),
    ("KD",    "kinh doanh"),
    ("CNTT",  "công nghệ thông tin"),
    ("KHCN",  "khoa học công nghệ"),
    # Địa điểm / kênh
    ("MS",    "microsoft teams"),
    ("GG",    "google meet"),
    ("GM",    "google meet"),
    ("SK",    "skype"),
    ("ZL",    "zalo"),
    # Thời gian
    ("SN",    "sáng nay"),
    ("CN",    "chiều nay"),
    ("TN",    "tối nay"),
    ("SM",    "sáng mai"),
    ("HN",    "hôm nay"),
    # Sức khoẻ / sinh hoạt
    ("UT",    "uống thuốc"),
    ("TTD",   "tập thể dục"),
    ("CB",    "chạy bộ"),
    ("KBS",   "kiểm tra sức khoẻ"),
]

_WORD_BOUNDARY = r"(?<![A-ZÀ-Ỵa-zà-ỵ0-9]){}(?![A-ZÀ-Ỵa-zà-ỵ0-9])"


# ── Các bước xử lý ────────────────────────────────────────────────────────────

def _strip_fillers(text: str) -> str:
    """Xoá cụm mở đầu và từ đuôi không mang thông tin."""
    # Lặp để xử lý nhiều lớp: "Nhớ nhé, nha, 20h họp đó nhé"
    for _ in range(3):
        text = _FILLER_PREFIX.sub("", text)
        text = _FILLER_SUFFIX.sub("", text)
        text = text.strip(" ,!.\n")
    return text


def _handle_parentheses(text: str) -> str:
    """Giữ nội dung trong ngoặc, bỏ ngoặc: "(phòng họp)" → "phòng họp"."""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\(([^()]*)\)", r" \1 ", text)
    return text


def _normalize_symbols(text: str) -> str:
    """Chuẩn hoá ký hiệu đặc biệt."""
    text = re.sub(r"\s*@\s*",          " tại ",  text)   # @ → tại
    text = re.sub(r"#\S+",             "",        text)   # hashtag → bỏ
    text = re.sub(r"(\w)\s*/\s*(\w)",  r"\1 \2",  text)   # "/" → khoảng trắng
    text = re.sub(r"[,،]+",            " ",       text)   # dấu phẩy → khoảng trắng
    return text


def _normalize_grammar(text: str) -> str:
    """
    Chuẩn hoá từ ngữ pháp / đại từ không mang thông tin entity.

    "để mai em thêm..."       → "mai thêm..."
    "lớp mình sẽ học"         → "học"
    "sẽ"                      → ""
    """
    # "để [TIME_WORD]" — bỏ "để", giữ time word
    # Khớp: để hôm nay / để mai / để sáng mai / để tối nay...
    text = re.sub(
        r"\bđể\s+(?="
        r"(?:hôm nay|ngày mai|mai|sáng mai|chiều mai|tối nay|sáng nay|chiều nay"
        r"|thứ\s*\w+|tuần sau|tuần tới|\d{1,2}h|\d{1,2}:\d{2})"
        r")",
        "", text, flags=re.IGNORECASE,
    )
    # Đại từ ngôi 1 đứng một mình làm chủ ngữ (không phải PARTNER)
    text = re.sub(
        r"\b(tôi|mình|em|anh|chị|tụi\s*mình|lớp\s*mình|chúng\s*mình"
        r"|bọn\s*mình|chúng\s*ta|chúng\s*tôi)\s*(sẽ|se)?\b",
        " ", text, flags=re.IGNORECASE,
    )
    # Trợ động từ tương lai còn sót
    text = re.sub(r"\bsẽ\b", "", text, flags=re.IGNORECASE)
    return text


def _expand_abbreviations(text: str) -> str:
    """Thay viết tắt bằng dạng đầy đủ (case-insensitive, word-boundary)."""
    for abbr, full in ABBREVIATIONS:
        pattern = _WORD_BOUNDARY.format(re.escape(abbr))
        text = re.sub(pattern, full, text, flags=re.IGNORECASE)
    return text


def _clean_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ── API công khai ─────────────────────────────────────────────────────────────

def preprocess(text: str) -> str:
    """
    Chuẩn hoá văn bản không chính thống trước khi đưa vào NER.

    Ví dụ:
      "Nhớ nhé, 20h họp dự án ở phòng họp tầng 3 đó"
      → "20h họp dự án ở phòng họp tầng 3"

      "20:00 họp DA @ tầng 3 (phòng họp)"
      → "20:00 họp dự án tại tầng 3 phòng họp"

      "tối thứ 3 tuần sau lớp mình sẽ học môn còn lại của cô Dung nhé"
      → "tối thứ 3 tuần sau học môn còn lại của cô Dung"

      "để mai em thêm phần ý vào xem có bị tụt không"
      → "mai thêm phần ý vào"
    """
    text = _strip_fillers(text)
    text = _handle_parentheses(text)
    text = _normalize_symbols(text)
    text = _normalize_grammar(text)
    text = _expand_abbreviations(text)
    text = _clean_whitespace(text)
    return text

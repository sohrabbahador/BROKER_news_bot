"""تاریخ شمسی و ساعت تهران: تبدیل، برچسب‌ها، تقویم، و تحلیل ساعت ورودی."""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def fa_to_en(value):
    return str(value).translate(_DIGITS)

def jalali_to_gregorian(jy, jm, jd):
    jy -= 979; jm -= 1; jd -= 1
    j_day_no = 365 * jy + (jy // 33) * 8 + ((jy % 33 + 3) // 4)
    j_day_no += sum([31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29][:jm]) + jd
    g_day_no = j_day_no + 79
    gy = 1600 + 400 * (g_day_no // 146097)
    g_day_no %= 146097
    leap = True
    if g_day_no >= 36525:
        g_day_no -= 1
        gy += 100 * (g_day_no // 36524)
        g_day_no %= 36524
        if g_day_no >= 365:
            g_day_no += 1
        else:
            leap = False
    gy += 4 * (g_day_no // 1461)
    g_day_no %= 1461
    if g_day_no >= 366:
        leap = False
        g_day_no -= 1
        gy += g_day_no // 365
        g_day_no %= 365
    mdays = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 12 and g_day_no >= mdays[gm]:
        g_day_no -= mdays[gm]
        gm += 1
    return gy, gm + 1, g_day_no + 1

def gregorian_to_jalali(gy, gm, gd):
    mdays = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gy2, gm2, gd2 = gy - 1600, gm - 1, gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += sum(mdays[:gm2]) + gd2
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm = 1
    while jm <= 11 and j_day_no >= (31 if jm <= 6 else 30):
        j_day_no -= 31 if jm <= 6 else 30
        jm += 1
    return jy, jm, j_day_no + 1

def tehran_now():
    return datetime.now(TEHRAN)

def today_jalali():
    n = tehran_now()
    return gregorian_to_jalali(n.year, n.month, n.day)

def datetime_label(dt):
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d} ساعت {dt:%H:%M} (تهران)"

def month_days(jy, jm):
    a = jalali_to_gregorian(jy, jm, 1)
    b = jalali_to_gregorian(jy + 1, 1, 1) if jm == 12 else jalali_to_gregorian(jy, jm + 1, 1)
    return (date(*b) - date(*a)).days

def parse_time(text):
    """«۱۸:۳۰»، «18:30»، «۱۸٫۳۰» یا «18.30» → (18, 30)؛ در غیر این صورت ValueError."""
    t = fa_to_en(text).strip().replace("٫", ":").replace("：", ":").replace(".", ":")
    m = re.fullmatch(r"(\d{1,2})\s*:\s*(\d{2})", t)
    if not m:
        raise ValueError("ساعت را مثل ۱۸:۳۰ وارد کن")
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh > 23 or mm > 59:
        raise ValueError("ساعت نامعتبر است")
    return hh, mm

def to_timestamp(jy, jm, jd, hh, mm):
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    return datetime(gy, gm, gd, hh, mm, tzinfo=TEHRAN).timestamp()

def calendar_rows(jy, jm, draft_id):
    """صفحه‌کلید تقویم یک ماه شمسی؛ هفته از شنبه شروع می‌شود."""
    gy, gm, gd = jalali_to_gregorian(jy, jm, 1)
    offset = (date(gy, gm, gd).weekday() + 2) % 7
    cells = [None] * offset + list(range(1, month_days(jy, jm) + 1))
    while len(cells) % 7:
        cells.append(None)
    today = today_jalali()
    rows = [
        [{"text": "‹ ماه قبل", "callback_data": f"calprev:{draft_id}:{jy}:{jm}"},
         {"text": f"{MONTHS[jm - 1]} {jy}", "callback_data": "calnoop"},
         {"text": "ماه بعد ›", "callback_data": f"calnext:{draft_id}:{jy}:{jm}"}],
        [{"text": d, "callback_data": "calnoop"} for d in ["ش", "ی", "د", "س", "چ", "پ", "ج"]],
    ]
    for i in range(0, len(cells), 7):
        row = []
        for day in cells[i:i + 7]:
            if day is None:
                row.append({"text": "·", "callback_data": "calnoop"})
            else:
                label = f"〔{day}〕" if (jy, jm, day) == today else str(day)
                row.append({"text": label, "callback_data": f"calday:{draft_id}:{jy}:{jm}:{day}"})
        rows.append(row)
    return rows

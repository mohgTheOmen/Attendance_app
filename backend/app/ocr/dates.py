"""Find the date of a paper attendance list: written on the sheet, or when the photo was taken."""
import io
import re
from datetime import date, datetime

from PIL import Image

from app.ocr.matching import ascii_upper

MONTHS = {
    "JAN": 1, "IAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "MAI": 5, "JUN": 6, "IUN": 6,
    "JUL": 7, "IUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "NOI": 11, "DEC": 12,
}
# "26 Oct", "26 octombrie 2026", "3-MAR-26"
WORD_DATE = re.compile(r"\b(\d{1,2})\s*[.\-/ ]?\s*(" + "|".join(MONTHS) + r")[A-Z]*\.?(?:\s*[.\-/ ]?\s*(\d{2,4}))?\b")
# "26.10.2026", "26/10", "26-10-26"
NUM_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?\b")
ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")


def _make(day: int, month: int, year: int | None, today: date) -> date | None:
    years = [year + 2000 if year is not None and year < 100 else year] if year else [today.year, today.year - 1]
    for y in years:  # without a year, take the most recent one that isn't in the future
        try:
            d = date(y, month, day)
        except ValueError:
            continue
        if year or d <= today:
            return d
    return None


def find_date(lines: list[str], today: date | None = None) -> tuple[date | None, str]:
    """Return (date, the text it came from), or (None, "") when no plausible date is written."""
    today = today or date.today()
    for raw in lines:
        text = ascii_upper(raw)
        if m := ISO_DATE.search(text):
            if d := _make(int(m[3]), int(m[2]), int(m[1]), today):
                return d, m[0]
        if m := WORD_DATE.search(text):
            if d := _make(int(m[1]), MONTHS[m[2][:3]], int(m[3]) if m[3] else None, today):
                return d, raw.strip()
        if m := NUM_DATE.search(text):
            if 1 <= int(m[2]) <= 12 and (d := _make(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, today)):
                return d, m[0]
    return None, ""


def photo_taken(data: bytes) -> date | None:
    """Camera capture date from EXIF (DateTimeOriginal, else DateTime)."""
    try:
        exif = Image.open(io.BytesIO(data)).getexif()
        value = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
        return datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S").date() if value else None
    except (OSError, ValueError, TypeError):
        return None

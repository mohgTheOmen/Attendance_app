"""Correction + deduplication: map noisy OCR lines onto known users.

Each line is scored against every candidate with a blend of fuzzy measures that tolerate
OCR errors (letters swapped, words split or merged, junk around the name). Lines are then
assigned to users one-to-one, best score first, so two lines never claim the same person and
a line that loses its best candidate falls back to its next best.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz

GROUP_CODE = re.compile(r"\b\d{3,4}\s*[A-Z]{1,2}\b")  # e.g. 1241EA (OCR often garbles it)
NOISE_WORDS = re.compile(r"\b(ERASMUS|ABSENT|PREZENT|PRESENT)\b")
# Dates in headers ("26 Oct", "3 martie 2026"). A month word only counts when a day number is
# next to it, so names like MARIA or OCTAVIAN are left alone.
MONTH_NAMES = (r"JANUARY|IANUARIE|FEBRUARY|FEBRUARIE|MARCH|MARTIE|APRIL|APRILIE|MAY|MAI|JUNE|IUNIE|JULY|IULIE|"
               r"AUGUST|SEPTEMBER|SEPTEMBRIE|OCTOBER|OCTOMBRIE|NOVEMBER|NOIEMBRIE|DECEMBER|DECEMBRIE|"
               r"JAN|IAN|FEB|MAR|APR|JUN|IUN|JUL|IUL|AUG|SEPT|SEP|OCT|NOV|NOI|DEC")
MONTHS = re.compile(rf"\b\d{{1,2}}\s*[.\-/]?\s*({MONTH_NAMES})\b\.?(\s*\d{{2,4}})?")
LEADING_NUMBER = re.compile(r"^[^A-Z]*[A-Z0-9]{0,2}\s*[)\]}|]\s*")  # "4)", "10)", "UM)" (garbled "11)")


def ascii_upper(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().upper()


def normalize_line(raw: str) -> str:
    s = ascii_upper(raw)
    s = MONTHS.sub(" ", NOISE_WORDS.sub(" ", GROUP_CODE.sub(" ", s)))
    s = LEADING_NUMBER.sub("", s)
    s = re.sub(r"[^A-Z ]+", " ", s)
    return " ".join(s.split())


def split_name(full_name: str) -> tuple[str, str]:
    """'IONESCU L.C. Ștefan-Andrei' -> ('IONESCU', 'STEFAN ANDREI').
    Roster style (all-caps surname first) is detected; otherwise 'Given Surname' is assumed."""
    tokens = full_name.split()
    surname = []
    while tokens and tokens[0].isupper() and len(tokens[0].rstrip(".")) > 1 and not tokens[0].endswith("."):
        surname.append(tokens.pop(0))
    if not surname and len(tokens) > 1:  # "Alice Johnson"
        surname = [tokens.pop()]
    given = [t for t in tokens if not t.endswith(".")]
    return ascii_upper(" ".join(surname)), ascii_upper(" ".join(given).replace("-", " "))


@dataclass
class Candidate:
    user_id: int
    full_name: str
    in_audience: bool = True
    surname: str = field(init=False)
    given: str = field(init=False)

    def __post_init__(self):
        self.surname, self.given = split_name(self.full_name)


def score(line: str, c: Candidate) -> float:
    """0-100. Weighted towards the surname, which people always write in full."""
    if not line:
        return 0.0
    words = line.split()
    # OCR splits and merges words, so also try adjacent pairs, joined and spaced
    windows = words + [a + b for a, b in zip(words, words[1:])] + [f"{a} {b}" for a, b in zip(words, words[1:])]
    s_surname = max(fuzz.ratio(c.surname, w) for w in windows)
    s_given = max((fuzz.ratio(g, w) for g in c.given.split() for w in windows), default=0)
    full = f"{c.surname} {c.given}"
    s_full = fuzz.token_set_ratio(line, full)
    s_partial = fuzz.partial_ratio(full, line)
    return round(0.45 * s_surname + 0.25 * s_given + 0.15 * s_full + 0.15 * s_partial, 1)


@dataclass
class LineResult:
    index: int
    image_index: int
    raw: str
    normalized: str
    status: str = "unmatched"  # matched | review | unmatched | duplicate | already_present | ignored
    user_id: int | None = None
    score: float = 0.0
    in_audience: bool = True
    suggestions: list[dict] = field(default_factory=list)


def match_lines(
    lines: list[tuple[int, str]],
    candidates: list[Candidate],
    *,
    already_present: set[int] = frozenset(),
    match_threshold: float = 70,
    review_threshold: float = 55,
) -> list[LineResult]:
    """lines: (image_index, raw_text). Returns one result per line, in input order."""
    results = [LineResult(i, img, raw, normalize_line(raw)) for i, (img, raw) in enumerate(lines)]
    by_id = {c.user_id: c for c in candidates}

    scores: dict[int, list[tuple[float, int]]] = {}
    seen_text: dict[str, int] = {}
    for r in results:
        if not any(len(w) >= 3 for w in r.normalized.split()):
            r.status = "ignored"  # headers like "S1", dates, grades, stray marks
            continue
        if r.normalized in seen_text:  # same text read twice (e.g. overlapping photos)
            r.status = "duplicate"
            continue
        seen_text[r.normalized] = r.index
        ranked = sorted(((score(r.normalized, c), c.user_id) for c in candidates), reverse=True)
        scores[r.index] = ranked
        r.suggestions = [
            {"user_id": uid, "full_name": by_id[uid].full_name, "score": s} for s, uid in ranked[:3]
        ]

    # A strong match on someone another line also matches strongly = the same person written twice.
    strong: dict[int, int] = {}
    for idx, ranked in sorted(scores.items(), key=lambda kv: -kv[1][0][0] if kv[1] else 0):
        if ranked and ranked[0][0] >= 85:
            uid = ranked[0][1]
            if uid in strong:
                results[idx].status, results[idx].user_id, results[idx].score = "duplicate", uid, ranked[0][0]
            else:
                strong[uid] = idx

    # One-to-one assignment, best pairs first.
    pairs = sorted(
        ((s, idx, uid) for idx, ranked in scores.items() if results[idx].status != "duplicate"
         for s, uid in ranked if s >= review_threshold),
        reverse=True,
    )
    used_lines, used_users = set(), set()
    for s, idx, uid in pairs:
        if idx in used_lines or uid in used_users:
            continue
        used_lines.add(idx)
        used_users.add(uid)
        r = results[idx]
        r.user_id, r.score, r.in_audience = uid, s, by_id[uid].in_audience
        if uid in already_present:
            r.status = "already_present"
        else:
            r.status = "matched" if s >= match_threshold else "review"
    for r in results:  # exact re-reads point at whoever the first reading matched
        if r.status == "duplicate" and r.user_id is None and r.normalized in seen_text:
            first = results[seen_text[r.normalized]]
            r.user_id, r.score, r.in_audience = first.user_id, first.score, first.in_audience
    return results

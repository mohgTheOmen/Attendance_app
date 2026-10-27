"""Run the OCR pipeline on an image against the users in the database and print the result.
Nothing is written.

Usage:  python -m app.ocr.evaluate path/to/list.jpg [--engine tesseract|azure]
"""
import argparse
import sys
import time
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import Role, User
from app.ocr.engines import ENGINES
from app.ocr.matching import Candidate, match_lines

MARK = {"matched": "OK ", "review": "?  ", "unmatched": "-  ", "duplicate": "dup", "ignored": "   ",
        "already_present": "had"}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("images", type=Path, nargs="+")
    parser.add_argument("--engine", choices=list(ENGINES), default="tesseract")
    args = parser.parse_args()

    started = time.perf_counter()
    lines = [(i, t) for i, p in enumerate(args.images) for t in ENGINES[args.engine](p.read_bytes())]
    ocr_s = time.perf_counter() - started
    with SessionLocal() as db:
        users = db.scalars(select(User).where(User.is_active.is_(True), User.role == Role.user)).all()
        candidates = [Candidate(u.id, u.full_name) for u in users]
        names = {u.id: u.full_name for u in users}
    s = get_settings()
    results = match_lines(lines, candidates, match_threshold=s.ocr_match_threshold,
                          review_threshold=s.ocr_review_threshold)

    for r in results:
        who = names.get(r.user_id, "")
        if r.status == "unmatched" and r.suggestions:
            who = f"(best guess {r.suggestions[0]['full_name']} @ {r.suggestions[0]['score']})"
        print(f"{MARK.get(r.status, r.status)} {r.score:5.1f}  {r.raw[:34]:34}  {who}")
    counts = {k: sum(r.status == k for r in results) for k in MARK}
    print(f"\n{len(lines)} lines in {ocr_s:.1f}s with {args.engine}: "
          + ", ".join(f"{k} {v}" for k, v in counts.items() if v))


if __name__ == "__main__":
    main()

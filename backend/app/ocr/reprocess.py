"""Re-read an uncommitted list import from its stored photos.

Usage: python -m app.ocr.reprocess IMPORT_ID
"""

import argparse
import json

from app.db import SessionLocal
from app.models import Event, OcrImport
from app.ocr.dates import find_date
from app.ocr.engines import ENGINES
from app.routers.ocr import _match
from app.storage import photo_abspath


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("import_id", type=int)
    args = parser.parse_args()

    with SessionLocal() as db:
        imp = db.get(OcrImport, args.import_id)
        if imp is None:
            parser.error("Import not found")
        if imp.committed_at is not None:
            parser.error("Cannot re-read a committed import")

        lines = [(i, text)
                 for i, path in enumerate(json.loads(imp.image_paths))
                 for text in ENGINES[imp.engine](photo_abspath(path).read_bytes())]
        event = db.get(Event, imp.event_id) if imp.event_id else None
        imp.raw_text = "\n".join(f"[{i}] {text}" for i, text in lines)
        imp.result = json.dumps(_match(db, lines, event))
        imp.detected_date, imp.date_text = find_date([text for _, text in lines])
        db.commit()
        print(f"Import {imp.id}: {len(lines)} OCR lines, {len(json.loads(imp.result))} review entries")


if __name__ == "__main__":
    main()

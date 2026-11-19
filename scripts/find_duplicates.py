"""
Find (and optionally remove) duplicate documents uploaded before v1.0 added upload hashing.

Old documents have no stored file hash, so duplicates are detected by their
extracted text: same workspace + identical non-empty text. The OLDEST copy is kept.

    python scripts/find_duplicates.py            # dry run: list duplicate groups
    python scripts/find_duplicates.py --apply    # soft-delete the extra copies

--apply does what the Delete button does: removes the copies' chunks and marks them
deleted. The chunks can't be restored, but re-uploading the file brings it back.
Run from the repository root with the backend venv's Python.
"""
import argparse
import hashlib
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.chdir(BACKEND)  # run from backend/, like the API (settings read the root .env by absolute path)

from app.db.models import Chunk, Document  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def duplicate_groups(db):
    groups = defaultdict(list)
    rows = (
        db.query(Document)
        .filter(Document.deleted_at.is_(None), Document.status != "failed")
        .order_by(Document.id)
        .all()
    )
    for doc in rows:
        text = (doc.raw_text or "").strip()
        if not text:
            continue
        key = (doc.workspace_id, hashlib.sha256(text.encode("utf-8")).hexdigest())
        groups[key].append(doc)
    return [docs for docs in groups.values() if len(docs) > 1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="soft-delete the extra copies")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        groups = duplicate_groups(db)
        if not groups:
            print("No duplicate documents found.")
            return 0
        extra = 0
        for docs in groups:
            keep, *copies = docs
            extra += len(copies)
            print(f"workspace {keep.workspace_id}: keep #{keep.id} {keep.filename!r}; "
                  f"duplicates: {', '.join(f'#{d.id} {d.filename!r}' for d in copies)}")
        print(f"\n{len(groups)} group(s), {extra} extra cop{'y' if extra == 1 else 'ies'}.")
        if not args.apply:
            print("Dry run: nothing changed. Re-run with --apply to remove the extra copies.")
            return 0
        now = datetime.now(timezone.utc)
        for docs in groups:
            for doc in docs[1:]:
                db.query(Chunk).filter(Chunk.document_id == doc.id).delete(synchronize_session=False)
                doc.deleted_at = now
        db.commit()
        print(f"Removed {extra} duplicate document(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

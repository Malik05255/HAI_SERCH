import os
import time
from pathlib import Path

from app.maintenance import prune_orphan_files


def test_prune_orphan_files_keeps_referenced_and_fresh_uploads(tmp_path: Path) -> None:
    account = tmp_path / "account"
    analysis = account / ".analysis"
    analysis.mkdir(parents=True)

    referenced = account / "referenced.jpg"
    expired = account / "expired.jpg"
    fresh = account / "fresh.jpg"
    for path in (referenced, expired, fresh):
        path.write_bytes(b"data")

    expired_cache = analysis / "expired.jpg.json"
    expired_cache.write_text("{}", encoding="utf-8")

    now = time.time()
    old = now - 48 * 3600
    os.utime(referenced, (old, old))
    os.utime(expired, (old, old))

    removed = prune_orphan_files(
        tmp_path,
        {str(referenced.resolve())},
        cutoff_epoch=now - 24 * 3600,
    )

    assert removed == 1
    assert referenced.exists()
    assert fresh.exists()
    assert not expired.exists()
    assert not expired_cache.exists()

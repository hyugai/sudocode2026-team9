"""Utilities shared by the synthetic dataset stages."""

import errno
import os
from pathlib import Path
from uuid import uuid4


def promote_latest(stage_dir: Path, run_folder_name: str) -> None:
    """Atomically publish a completed run using a relative pointer."""
    target = Path("runs") / run_folder_name
    temporary = stage_dir / f".latest-{uuid4().hex}"
    fallback = stage_dir / "latest_path.txt"

    try:
        try:
            os.symlink(target, temporary, target_is_directory=True)
        except OSError as error:
            unsupported = {errno.EACCES, errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP}
            if error.errno not in unsupported and getattr(error, "winerror", None) != 1314:
                raise
            temporary.write_text(target.as_posix() + "\n", encoding="utf-8")
            os.replace(temporary, fallback)
        else:
            os.replace(temporary, stage_dir / "latest")
            fallback.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)

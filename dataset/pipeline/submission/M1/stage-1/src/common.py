"""Utilities and file names shared by the synthetic dataset stages."""

from datetime import datetime
import errno
import os
from pathlib import Path
import re
from uuid import uuid4


CUSTOMERS_FILE = "customers.json"
BLUEPRINTS_FILE = "blueprints.jsonl"
TRANSCRIPTS_FILE = "raw-scenarios.jsonl"
GENERATION_LOG_FILE = "generation-log.json"
QUALITY_REPORT_FILE = "quality-report.jsonl"
LEGACY_FILENAMES = {
    CUSTOMERS_FILE: "stage1_customers.json",
    BLUEPRINTS_FILE: "stage1_blueprints.jsonl",
    TRANSCRIPTS_FILE: "raw_scenarios.jsonl",
    GENERATION_LOG_FILE: "generation_log.json",
    QUALITY_REPORT_FILE: "quality_report.jsonl",
    "quality-report.manifest.json": "quality_report.manifest.json",
}
SIMULATED_LOCALITY = re.compile(r"(?:^|, )(?:phường|xã) mô phỏng [^,]+(?:, |$)")


def is_simulated_delivery_address(value: str) -> bool:
    """Recognize the explicit locality marker in the CRM delivery address catalog."""
    return isinstance(value, str) and len(value.splitlines()) == 1 and bool(SIMULATED_LOCALITY.search(value))


def find_artifact(directory: Path, filename: str) -> Path:
    """Find an artifact by its current name or its archived name."""
    current = directory / filename
    legacy_name = LEGACY_FILENAMES.get(filename)
    if legacy_name is not None and not current.exists():
        archived = directory / legacy_name
        if archived.exists():
            return archived
    return current


def run_name(tier: str, timestamp: datetime) -> str:
    return f"run-{tier}-{timestamp:%Y%m%d-%H%M}"


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

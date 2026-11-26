"""Reproduce the committed Stage 3 export from its offline inputs."""

from pathlib import Path
from shutil import copyfile
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "dataset/pipeline"
STAGE3 = PIPELINE / "stage-3"
CATALOG = PIPELINE / "stage-1/input/catalog"


def snapshot(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_text(encoding="utf-8")
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in {".json", ".jsonl"}
    }


def main():
    sys.path.insert(0, str(STAGE3 / "src"))
    from finalize import finalize

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        btc = root / "btc"
        # The notebook expects the organizer bundle layout for these two inputs.
        for source, name in (
            (CATALOG / "crm_seed.json", "BTC-Data-Vong1-TEAMS/catalog/crm_seed.json"),
            (ROOT / "dataset/organizer/eval/reference_eval.py",
             "BTC-cap-nhat-11-2026/eval/reference_eval.py"),
        ):
            target = btc / name
            target.parent.mkdir(parents=True, exist_ok=True)
            copyfile(source, target)

        output = root / "output"
        stats = finalize(
            STAGE3 / "input",
            output,
            btc_dir=btc,
            venue_catalog=CATALOG / "public-delivery-addresses.json",
            batch_size=20,
        )
        expected = snapshot(STAGE3 / "output")
        actual = snapshot(output)
        changed = sorted(name for name in expected.keys() | actual.keys()
                         if expected.get(name) != actual.get(name))
        if changed:
            raise SystemExit(f"Stage 3 export differs in {len(changed)} files: {', '.join(changed[:10])}")
        print(f"Verified {stats['total_journeys']} scenarios and their Stage 3 audit files.")


if __name__ == "__main__":
    main()

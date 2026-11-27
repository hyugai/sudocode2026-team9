#!/usr/bin/env python3
"""
Optional converter for an explicitly supplied external JSONL scenario file.

Current scenarios already exist as individual JSON files in
``dataset/pipeline/stage-3/output/m1-v1`` and can be evaluated directly.

Usage:
    python src/eval/prepare_scenarios.py --src /path/to/scenarios.jsonl --out /tmp/scenarios

Each JSONL record becomes one ``<scenario_id>.json`` file in the output directory.
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent          # src/eval/
REPO_ROOT = HERE.parent.parent                  # sudo_code_2026-group_9/

DEFAULT_OUT = REPO_ROOT / "outputs" / "eval" / "imported-scenarios"


def unpack(src: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    with src.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            scenario = json.loads(line)
            sid = scenario.get("scenario_id", f"SC-UNKNOWN-{count:03d}")
            dest = out / f"{sid}.json"
            dest.write_text(
                json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            count += 1
    print(f"[Unpack] {count} scenarios → {out}")


def main():
    parser = argparse.ArgumentParser(description="Tách JSONL scenarios thành JSON lẻ.")
    parser.add_argument("--src", required=True, help="File JSONL bên ngoài cần chuyển đổi")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Thư mục output")
    args = parser.parse_args()
    unpack(Path(args.src), Path(args.out))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Unpack scenarios JSONL → thư mục chứa từng file JSON lẻ.

Usage:
    python src/eval/prepare_scenarios.py
    python src/eval/prepare_scenarios.py --src dataset/iterative-refinement/02_scenarios_complete.jsonl
                                        --out dataset/iterative-refinement/scenarios

Mỗi dòng trong JSONL → một file `<scenario_id>.json` trong thư mục output.
"""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent          # src/eval/
REPO_ROOT = HERE.parent.parent                  # sudo_code_2026-group_9/

DEFAULT_SRC = REPO_ROOT / "dataset" / "iterative-refinement" / "02_scenarios_complete.jsonl"
DEFAULT_OUT = REPO_ROOT / "dataset" / "iterative-refinement" / "scenarios"


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
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="File JSONL đầu vào")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Thư mục output")
    args = parser.parse_args()
    unpack(Path(args.src), Path(args.out))


if __name__ == "__main__":
    main()

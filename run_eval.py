"""Run a single BTC M1 configuration over a supplied scenario directory."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from eval.generate_traces import main


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(submission=True)))

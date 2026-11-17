"""API-free regression runner with a machine-readable result, not fixed counts."""
from __future__ import annotations

import argparse
import time
import unittest
from pathlib import Path

from .common import HERE, write


class JsonResult(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()

    def record(self, test, status, detail=None):
        self.records.append({"test": test.id(), "status": status,
                             "seconds": round(time.monotonic() - self.started, 4), "detail": detail})

    def addSuccess(self, test):
        super().addSuccess(test); self.record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err); self.record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err); self.record(test, "failed", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason); self.record(test, "skipped", reason)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(HERE / "tests"))
    def result_class(*a, **kw):
        result = JsonResult(*a, **kw); result.records = []; return result
    result = unittest.TextTestRunner(verbosity=2, resultclass=result_class).run(suite)
    write(args.report, {"status": "passed" if result.wasSuccessful() else "failed",
                        "tests_run": result.testsRun, "failures": len(result.failures),
                        "errors": len(result.errors), "skipped": len(result.skipped), "tests": result.records})
    return 0 if result.wasSuccessful() else 2


if __name__ == "__main__":
    raise SystemExit(main())

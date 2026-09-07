#!/usr/bin/env python3
"""Run explicit pyDuckHunt validation lanes with visible unittest progress."""

from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def discover(start_directory: str) -> unittest.TestSuite:
    return unittest.defaultTestLoader.discover(
        start_dir=str(ROOT / start_directory),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )


def build_suite(lane: str, selected_tests: list[str]) -> unittest.TestSuite:
    if lane == "targeted":
        if not selected_tests:
            raise ValueError("the targeted lane requires at least one --test")
        return unittest.defaultTestLoader.loadTestsFromNames(selected_tests)

    suite = unittest.TestSuite()
    suite.addTests(discover("tests/unit"))
    suite.addTests(discover("tests/contract"))
    if lane == "full":
        suite.addTests(discover("tests/integration"))
        suite.addTests(discover("tests/replay"))
    return suite


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("targeted", "fast", "full"), required=True)
    parser.add_argument("--test", action="append", default=[], dest="tests")
    parser.add_argument(
        "--progress",
        action="store_true",
        help="show one compact progress bar and details only for failures",
    )
    return parser.parse_args(argv)


class CompactProgressResult(unittest.TextTestResult):
    """Keep successful test output quiet while preserving complete failures."""

    def __init__(
        self,
        stream: object,
        descriptions: bool,
        verbosity: int,
        *,
        lane: str,
        total: int,
    ) -> None:
        super().__init__(stream, descriptions, verbosity)
        self.lane = lane.title()
        self.total = total
        self.completed = 0
        self._interactive = bool(getattr(stream, "isatty", lambda: False)())

    def stopTest(self, test: unittest.case.TestCase) -> None:
        super().stopTest(test)
        self.completed += 1
        if self._interactive:
            self._render(final=False)

    def finish(self) -> None:
        self._render(final=True)

    def _render(self, *, final: bool) -> None:
        width = 20
        filled = width if self.total == 0 else width * self.completed // self.total
        bar = "█" * filled + "░" * (width - filled)
        status = "NOK" if self.failures or self.errors or self.unexpectedSuccesses else "OK"
        line = f"{self.lane:<9} [{bar}] {self.completed}/{self.total} {status}"
        if self._interactive and not final:
            self.stream.write("\r" + line)
            self.stream.flush()
            return
        if self._interactive:
            self.stream.write("\r" + line + "\n")
        else:
            self.stream.write(line + "\n")
        self.stream.flush()


def run_compact(suite: unittest.TestSuite, lane: str) -> unittest.TestResult:
    stream = unittest.runner._WritelnDecorator(sys.stderr)
    result = CompactProgressResult(
        stream,
        True,
        0,
        lane=lane,
        total=suite.countTestCases(),
    )
    result.buffer = True
    unittest.registerResult(result)
    result.startTestRun()
    try:
        suite(result)
    finally:
        result.stopTestRun()
    if not result.wasSuccessful():
        if result._interactive:
            stream.write("\n")
        result.printErrors()
    result.finish()
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        suite = build_suite(args.lane, args.tests)
    except ValueError as error:
        print(f"[KO] {error}", file=sys.stderr)
        return 2

    if args.progress:
        result = run_compact(suite, args.lane)
    else:
        print("pyDuckHunt validation")
        print("-" * 60)
        print(f"Lane     : {args.lane}")
        print(f"Selected : {suite.countTestCases()} test(s)")
        print("-" * 60)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

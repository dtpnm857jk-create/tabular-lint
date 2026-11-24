#!/usr/bin/env python3
"""Rerun every fixture, compare against fixtures/expected/, and print PASS/FAIL."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tabularlint.config import default_config, load_config_file
from tabularlint.lint import lint_path, should_fail

FIXTURES = ROOT / "fixtures"
EXPECTED = FIXTURES / "expected"


def fixture_files() -> list[Path]:
    return [
        p
        for p in sorted(FIXTURES.iterdir())
        if p.is_file() and p.suffix.lower() in {".csv", ".tsv"}
    ]


def load_spec(stem: str) -> dict:
    path = EXPECTED / f"{stem}.issues.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing expected issue spec: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def compare(result, spec: dict, config) -> list[str]:
    problems: list[str] = []
    if "encoding" in spec and result.encoding != spec["encoding"]:
        problems.append(
            f"encoding: actual {result.encoding!r}, expected {spec['encoding']!r}"
        )
    if "delimiter" in spec and result.delimiter != spec["delimiter"]:
        problems.append(
            f"delimiter: actual {result.delimiter!r}, expected {spec['delimiter']!r}"
        )
    if "bom" in spec and bool(result.bom) != bool(spec["bom"]):
        problems.append(f"bom: actual {result.bom}, expected {spec['bom']}")
    actual_codes = result.issue_codes()
    actual_set = set(actual_codes)
    missing = [code for code in spec.get("required", []) if code not in actual_set]
    if missing:
        problems.append(f"missing required issue codes: {missing} (got {actual_codes})")
    unexpected = [code for code in spec.get("forbidden", []) if code in actual_set]
    if unexpected:
        problems.append(f"unexpected issue codes: {unexpected}")
    if "exact" in spec and set(actual_codes) != set(spec["exact"]):
        problems.append(f"issue codes {actual_codes} != exact expected {spec['exact']}")
    expected_exit = spec.get("exit")
    if expected_exit is not None:
        # should_fail uses the default config unless the spec names another.
        fail = should_fail([result], config, strict=False)
        actual_exit = 1 if fail else 0
        if actual_exit != int(expected_exit):
            problems.append(
                f"exit code: actual {actual_exit}, expected {expected_exit}"
            )
    return problems


def main() -> int:
    files = fixture_files()
    if not files:
        print("FAIL  no fixtures found in", FIXTURES)
        return 1

    config = default_config()
    extra = FIXTURES / "tabularlint.json"
    if extra.is_file():
        config = load_config_file(extra)

    passed = 0
    failed = 0
    print(f"tabular-lint fixture run  ({len(files)} file(s))")
    print("-" * 60)

    for path in files:
        try:
            result = lint_path(path, config)
            spec = load_spec(path.stem)
            problems = compare(result, spec, config)
        except Exception as exc:  # noqa: BLE001 — surface unexpected errors as FAIL
            problems = [f"{type(exc).__name__}: {exc}"]
            result = None

        if problems:
            failed += 1
            print(f"FAIL  {path.name}")
            for item in problems:
                print(f"      {item}")
        else:
            passed += 1
            codes = ",".join(result.issue_codes()) if result and result.issues else "none"
            print(
                f"PASS  {path.name}  "
                f"encoding={result.encoding}  "
                f"delimiter={result.delimiter_name}  "
                f"issues={codes}"
            )

    print("-" * 60)
    print(f"{passed} passed, {failed} failed, {len(files)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

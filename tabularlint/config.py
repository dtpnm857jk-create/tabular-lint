"""Load a small JSON config for tabular-lint. Standard library only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Checks named in the README. Values: "error", "warning", or "off".
DEFAULT_CHECKS: dict[str, str] = {
    "ragged_row": "error",
    "encoding_non_utf8": "warning",
    "bom": "warning",
    "mixed_line_endings": "warning",
    "mixed_delimiters": "error",
    "duplicate_header": "error",
    "empty_header": "error",
    "trailing_whitespace": "warning",
}

DEFAULT_INCLUDE = ("*.csv", "*.tsv", "*.CSV", "*.TSV")
CONFIG_FILENAMES = (".tabularlint.json", "tabularlint.json")


def default_config() -> dict[str, Any]:
    return {
        "include": list(DEFAULT_INCLUDE),
        "exclude": [],
        "fail_on": "error",  # "error" | "warning"
        "checks": dict(DEFAULT_CHECKS),
    }


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    cfg = default_config()
    if "include" in raw:
        if not isinstance(raw["include"], list) or not all(
            isinstance(x, str) for x in raw["include"]
        ):
            raise ValueError("include must be a list of strings")
        cfg["include"] = list(raw["include"])
    if "exclude" in raw:
        if not isinstance(raw["exclude"], list) or not all(
            isinstance(x, str) for x in raw["exclude"]
        ):
            raise ValueError("exclude must be a list of strings")
        cfg["exclude"] = list(raw["exclude"])
    if "fail_on" in raw:
        if raw["fail_on"] not in {"error", "warning"}:
            raise ValueError("fail_on must be 'error' or 'warning'")
        cfg["fail_on"] = raw["fail_on"]
    if "checks" in raw:
        if not isinstance(raw["checks"], dict):
            raise ValueError("checks must be an object")
        checks = dict(DEFAULT_CHECKS)
        for key, value in raw["checks"].items():
            if not isinstance(key, str):
                raise ValueError("check names must be strings")
            if value not in {"error", "warning", "off"}:
                raise ValueError(
                    f"check {key!r} must be 'error', 'warning', or 'off'"
                )
            checks[key] = value
        cfg["checks"] = checks
    return cfg


def load_config_file(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return validate_config(raw)


def find_config(start: Path | None = None) -> Path | None:
    """Search this directory and its parents for a config file."""
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    roots = [current, *current.parents]
    for directory in roots:
        for name in CONFIG_FILENAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None

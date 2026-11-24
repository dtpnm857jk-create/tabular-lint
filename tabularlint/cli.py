"""Command-line interface for tabular-lint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tabularlint import __version__
from tabularlint.config import default_config, find_config, load_config_file
from tabularlint.lint import (
    FileReport,
    iter_input_files,
    lint_path,
    render_human,
    render_json,
    should_fail,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tabularlint",
        description=(
            "Lint CSV/TSV files for inconsistent columns, encoding/BOM issues, "
            "mixed delimiters or line endings, duplicate or empty headers, "
            "and trailing whitespace. Standard library only."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Files or directories to check (directories are searched for *.csv and *.tsv)",
    )
    parser.add_argument(
        "--config",
        metavar="FILE",
        help="JSON config file (default: .tabularlint.json or tabularlint.json, walking parents)",
    )
    parser.add_argument(
        "--format",
        choices=("human", "json", "both"),
        default="human",
        help="Output format (default: human). 'both' prints human text, then JSON",
    )
    parser.add_argument(
        "--json-out",
        metavar="FILE",
        help="Also write the JSON report to this path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures (exit 1), regardless of fail_on in the config",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tabular-lint {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.config:
            config_path = Path(args.config)
            if not config_path.is_file():
                print(f"tabularlint: config not found: {config_path}", file=sys.stderr)
                return 2
            config = load_config_file(config_path)
        else:
            found = find_config(Path.cwd())
            config = load_config_file(found) if found else default_config()
    except ValueError as exc:
        print(f"tabularlint: {exc}", file=sys.stderr)
        return 2

    inputs = [Path(p) for p in args.paths]
    missing = [p for p in inputs if not p.exists()]
    if missing:
        for path in missing:
            print(f"tabularlint: path not found: {path}", file=sys.stderr)
        return 2

    files = iter_input_files(inputs, config)
    reports: list[FileReport] = []
    for path in files:
        try:
            reports.append(lint_path(path, config))
        except OSError as exc:
            print(f"tabularlint: {exc}", file=sys.stderr)
            return 2

    human = render_human(reports)
    payload = render_json(reports)
    if args.format == "human":
        sys.stdout.write(human)
    elif args.format == "json":
        sys.stdout.write(payload)
    else:
        sys.stdout.write(human)
        if not human.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.write(payload)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")

    return 1 if should_fail(reports, config, strict=bool(args.strict)) else 0

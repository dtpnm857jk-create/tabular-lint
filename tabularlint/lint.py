"""Inspect one or more tabular files and return structured issues."""

from __future__ import annotations

import csv
import fnmatch
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from tabularlint.detect import (
    classify_line_endings,
    decode_bytes,
    detect_delimiter,
    _count_unquoted,
    _delim_name,
    _logical_lines,
)

DEFAULT_EXTENSIONS = {".csv", ".tsv"}

SEVERITY_RANK = {"error": 2, "warning": 1, "info": 0}


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    count: int = 1
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "count": self.count,
        }
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass
class FileReport:
    path: str
    encoding: str
    bom: bool
    delimiter: str
    delimiter_name: str
    line_endings: list[str]
    row_count: int
    column_count: int
    issues: list[Issue]

    def issue_codes(self) -> list[str]:
        return [i.code for i in self.issues]

    def max_severity(self) -> str | None:
        if not self.issues:
            return None
        return max(self.issues, key=lambda i: SEVERITY_RANK.get(i.severity, 0)).severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "encoding": self.encoding,
            "bom": self.bom,
            "delimiter": self.delimiter,
            "delimiter_name": self.delimiter_name,
            "line_endings": self.line_endings,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "issues": [i.to_dict() for i in self.issues],
            "issue_codes": self.issue_codes(),
        }


def _enabled(config: dict[str, Any], code: str) -> str | None:
    """Return the configured severity, or None if the check is off / unknown."""
    level = config.get("checks", {}).get(code)
    if level in {None, "off"}:
        return None
    return level


def _issue(
    config: dict[str, Any],
    code: str,
    message: str,
    *,
    count: int = 1,
    details: list[str] | None = None,
    fallback_severity: str = "warning",
) -> Issue | None:
    severity = _enabled(config, code) or None
    if severity is None and code not in config.get("checks", {}):
        # Unknown codes should not appear; if a caller passes one, skip it.
        return None
    if severity is None:
        return None
    return Issue(
        code=code,
        severity=severity,
        message=message,
        count=count,
        details=details or [],
    )


def detect_mixed_delimiters(text: str, primary: str) -> dict[str, Any]:
    """Return evidence that more than one delimiter is in active use."""
    lines = [ln for ln in _logical_lines(text) if ln.strip()]
    if len(lines) < 2:
        return {"mixed": False, "details": []}
    delimiters = [",", "\t", ";", "|"]
    # For each delimiter, how many non-empty lines contain it (unquoted) at least once?
    per_delim: dict[str, list[int]] = {}
    for delim in delimiters:
        hits = []
        for i, line in enumerate(lines, start=1):
            n = _count_unquoted(line, delim)
            if n >= 1:
                hits.append(i)
        per_delim[delim] = hits

    primary_hits = set(per_delim.get(primary, []))
    rivals = []
    for delim, hits in per_delim.items():
        if delim == primary:
            continue
        # A rival must appear on at least two lines that do *not* contain the primary
        # delimiter, so a quoted comma inside a TSV does not count as mixed.
        exclusive = [n for n in hits if n not in primary_hits]
        if len(exclusive) >= 2:
            rivals.append((delim, exclusive))
        # Also: lines that contain BOTH, but with a field-count that only makes
        # sense if the rival is the real delimiter (e.g. tab-separated rows in
        # a mostly-comma file). Require exclusive evidence first for stability.
    if not rivals:
        return {"mixed": False, "details": []}
    details = []
    for delim, rows in rivals:
        preview = ", ".join(str(n) for n in rows[:8])
        details.append(
            f"{_delim_name(delim)} appears without the primary delimiter "
            f"on {len(rows)} line(s): {preview}"
        )
    return {"mixed": True, "details": details, "rivals": rivals}


def lint_bytes(
    data: bytes,
    *,
    label: str,
    config: dict[str, Any],
) -> FileReport:
    text, enc_info = decode_bytes(data)
    endings = classify_line_endings(data)
    delim_info = detect_delimiter(text)
    delim = delim_info["delimiter"]

    issues: list[Issue] = []

    if enc_info["bom"]:
        issue = _issue(
            config,
            "bom",
            (
                f"File starts with a {enc_info['bom_kind']} byte-order mark. "
                "Prefer UTF-8 without a BOM in source files."
            ),
        )
        if issue:
            issues.append(issue)

    if enc_info["encoding"] not in {"utf-8", "utf-8-sig"}:
        issue = _issue(
            config,
            "encoding_non_utf8",
            (
                f"Detected encoding {enc_info['encoding']} "
                f"(confidence {enc_info['confidence']:.2f}). "
                "Commit tables as UTF-8."
            ),
        )
        if issue:
            issues.append(issue)

    if endings["mixed"]:
        kinds = ", ".join(endings["kinds"])
        issue = _issue(
            config,
            "mixed_line_endings",
            (
                f"Mixed line endings detected ({kinds}; "
                f"CRLF={endings['crlf']}, LF={endings['lf']}, CR={endings['cr']})."
            ),
        )
        if issue:
            issues.append(issue)

    mixed = detect_mixed_delimiters(text, delim)
    if mixed["mixed"]:
        issue = _issue(
            config,
            "mixed_delimiters",
            (
                f"The file appears to mix delimiters. Primary guess is "
                f"{delim_info['name']}. " + " ".join(mixed["details"])
            ),
            count=len(mixed["details"]),
            details=mixed["details"],
        )
        if issue:
            issues.append(issue)

    rows = _parse_rows(text, delim)
    header, body, leading_empty = _split_header(rows)

    if leading_empty and not header and not body:
        # Empty or whitespace-only file: report empty_header if that check is on.
        issue = _issue(config, "empty_header", "The file has no header row.")
        if issue:
            issues.append(issue)
        return FileReport(
            path=label,
            encoding=enc_info["encoding"],
            bom=bool(enc_info["bom"]),
            delimiter=delim,
            delimiter_name=str(delim_info["name"]),
            line_endings=list(endings["kinds"]),
            row_count=0,
            column_count=0,
            issues=issues,
        )

    empty_positions = [i + 1 for i, name in enumerate(header) if name.strip() == ""]
    if empty_positions:
        issue = _issue(
            config,
            "empty_header",
            (
                f"{len(empty_positions)} header cell(s) are empty "
                f"(column {', '.join(str(i) for i in empty_positions)})."
            ),
            count=len(empty_positions),
            details=[f"column {i}" for i in empty_positions],
        )
        if issue:
            issues.append(issue)

    stripped_names = [name.strip() for name in header]
    seen: dict[str, list[int]] = {}
    for i, name in enumerate(stripped_names, start=1):
        if name == "":
            continue
        seen.setdefault(name, []).append(i)
    dups = {name: cols for name, cols in seen.items() if len(cols) > 1}
    if dups:
        details = [
            f"{name!r} appears in columns {', '.join(str(c) for c in cols)}"
            for name, cols in dups.items()
        ]
        issue = _issue(
            config,
            "duplicate_header",
            "Duplicate header name(s): " + "; ".join(details) + ".",
            count=sum(len(cols) - 1 for cols in dups.values()),
            details=details,
        )
        if issue:
            issues.append(issue)

    header_len = len(header)
    ragged = []
    for i, row in enumerate(body, start=2 + leading_empty):
        if len(row) != header_len:
            ragged.append((i, len(row)))
    if ragged:
        preview = ", ".join(f"row {i} has {n} field(s)" for i, n in ragged[:8])
        more = "" if len(ragged) <= 8 else f" and {len(ragged) - 8} more"
        issue = _issue(
            config,
            "ragged_row",
            (
                f"{len(ragged)} data row(s) have a field count different from the "
                f"header ({header_len} column(s)): {preview}{more}."
            ),
            count=len(ragged),
        )
        if issue:
            issues.append(issue)

    ws_hits: list[str] = []
    for c_i, name in enumerate(header, start=1):
        if name.endswith(" ") or name.endswith("\t"):
            ws_hits.append(f"header column {c_i}: {name!r}")
    for r_i, row in enumerate(body, start=2 + leading_empty):
        for c_i, cell in enumerate(row, start=1):
            if cell.endswith(" ") or cell.endswith("\t"):
                if len(ws_hits) < 12:
                    ws_hits.append(f"row {r_i}, column {c_i}: {cell!r}")
                elif len(ws_hits) == 12:
                    ws_hits.append("…")
    ws_count = sum(
        1
        for row in (header, *body)
        for cell in row
        if cell.endswith(" ") or cell.endswith("\t")
    )
    if ws_count:
        issue = _issue(
            config,
            "trailing_whitespace",
            f"Found {ws_count} field(s) with trailing whitespace.",
            count=ws_count,
            details=[h for h in ws_hits if h != "…"][:12],
        )
        if issue:
            issues.append(issue)

    return FileReport(
        path=label,
        encoding=enc_info["encoding"],
        bom=bool(enc_info["bom"]),
        delimiter=delim,
        delimiter_name=str(delim_info["name"]),
        line_endings=list(endings["kinds"]),
        row_count=len(body),
        column_count=header_len,
        issues=issues,
    )


def lint_path(path: Path, config: dict[str, Any]) -> FileReport:
    data = path.read_bytes()
    return lint_bytes(data, label=str(path), config=config)


def _parse_rows(text: str, delimiter: str) -> list[list[str]]:
    stream = io.StringIO(text, newline="")
    try:
        reader = csv.reader(
            stream,
            delimiter=delimiter,
            quotechar='"',
            doublequote=True,
            skipinitialspace=False,
            strict=False,
        )
        return [list(row) for row in reader]
    except csv.Error:
        rows: list[list[str]] = []
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if line == "" and not rows:
                continue
            try:
                parsed = next(
                    csv.reader(
                        [line],
                        delimiter=delimiter,
                        quotechar='"',
                        doublequote=True,
                        skipinitialspace=False,
                        strict=False,
                    )
                )
                rows.append(list(parsed))
            except csv.Error:
                rows.append(line.split(delimiter))
        if rows and rows[-1] == [""] and text.endswith(("\n", "\r")):
            rows.pop()
        return rows


def _split_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]], int]:
    leading = 0
    while leading < len(rows) and all(cell.strip() == "" for cell in rows[leading]):
        leading += 1
    if leading >= len(rows):
        return [], [], leading
    return rows[leading], rows[leading + 1 :], leading


def iter_input_files(
    paths: Iterable[Path], config: dict[str, Any]
) -> list[Path]:
    include = list(config.get("include") or DEFAULT_EXTENSIONS)
    exclude = list(config.get("exclude") or [])
    found: list[Path] = []
    seen: set[Path] = set()

    def allowed(path: Path) -> bool:
        rel = path.as_posix()
        name = path.name
        if exclude and any(
            fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat) for pat in exclude
        ):
            return False
        return any(
            fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat) for pat in include
        )

    for raw in paths:
        path = raw.resolve() if raw.exists() else raw
        if path.is_file():
            # Explicit files on the command line are always included, even if
            # the extension is unusual — the user asked us to lint that path.
            if path not in seen:
                found.append(path)
                seen.add(path)
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if not child.is_file():
                    continue
                if child.name.startswith("."):
                    continue
                if "/." in child.as_posix():
                    # Skip hidden directories like .git
                    continue
                if allowed(child) and child not in seen:
                    found.append(child)
                    seen.add(child)
            continue
        # Missing path: still yield it so the CLI can error clearly.
        if path not in seen:
            found.append(raw)
            seen.add(path)
    return found


def worst_rank(reports: list[FileReport]) -> int:
    rank = 0
    for report in reports:
        for issue in report.issues:
            rank = max(rank, SEVERITY_RANK.get(issue.severity, 0))
    return rank


def should_fail(reports: list[FileReport], config: dict[str, Any], strict: bool) -> bool:
    fail_on = "warning" if strict else config.get("fail_on", "error")
    threshold = SEVERITY_RANK["warning"] if fail_on == "warning" else SEVERITY_RANK["error"]
    return worst_rank(reports) >= threshold


def render_human(reports: list[FileReport]) -> str:
    if not reports:
        return "tabular-lint: no files to check\n"
    lines: list[str] = []
    for report in reports:
        status = "clean" if not report.issues else report.max_severity()
        lines.append(
            f"{report.path}: {status}  "
            f"(encoding={report.encoding}, delimiter={report.delimiter_name}, "
            f"rows={report.row_count}, cols={report.column_count})"
        )
        for issue in report.issues:
            lines.append(f"  [{issue.severity}] {issue.code}: {issue.message}")
            for detail in issue.details[:8]:
                lines.append(f"    - {detail}")
    errors = sum(
        1 for r in reports for i in r.issues if i.severity == "error"
    )
    warnings = sum(
        1 for r in reports for i in r.issues if i.severity == "warning"
    )
    files = len(reports)
    dirty = sum(1 for r in reports if r.issues)
    lines.append(
        f"{files} file(s) checked, {dirty} with issues, "
        f"{errors} error(s), {warnings} warning(s)"
    )
    return "\n".join(lines) + "\n"


def render_json(reports: list[FileReport]) -> str:
    errors = sum(1 for r in reports for i in r.issues if i.severity == "error")
    warnings = sum(1 for r in reports for i in r.issues if i.severity == "warning")
    payload = {
        "files": [r.to_dict() for r in reports],
        "summary": {
            "files": len(reports),
            "files_with_issues": sum(1 for r in reports if r.issues),
            "errors": errors,
            "warnings": warnings,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

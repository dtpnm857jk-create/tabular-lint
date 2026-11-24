"""Encoding, delimiter, and line-ending detection. Standard library only."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

# Detection order is a tie-breaker after scoring.
ENCODING_CANDIDATES = (
    "utf-8",
    "big5",
    "cp950",
    "gbk",
    "gb18030",
    "cp1252",
    "latin-1",
)

# A small set of characters that usually appear in Traditional vs Simplified text.
# Used only as a scoring hint when both Big5-family and GBK-family decodes succeed.
_TRADITIONAL_HINTS = set("國台灣語門東個時業與於號過這對發經開關電鄉後備註縣鄉鎮區條縣市")
_SIMPLIFIED_HINTS = set("国台湾语门东个时业与于号过这对发经开关电乡后备注县乡镇区条")

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN1_LETTER_RE = re.compile(r"[\u00c0-\u00ff]")


def sniff_bom(data: bytes) -> str | None:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if data.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return "utf-16-be"
    return None


def _score_decoded(text: str, encoding: str) -> float:
    score = 0.0
    for ch in text:
        o = ord(ch)
        if ch in "\t\r\n":
            continue
        if o < 32 or o == 127:
            score -= 50
        elif ch == "\ufffd":
            score -= 100

    cjk = len(_CJK_RE.findall(text))
    latin = len(_LATIN1_LETTER_RE.findall(text))
    trad = sum(1 for ch in text if ch in _TRADITIONAL_HINTS)
    simp = sum(1 for ch in text if ch in _SIMPLIFIED_HINTS)
    ascii_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    high = sum(1 for ch in text if ord(ch) >= 128)

    if encoding == "utf-8":
        # Valid UTF-8 always wins over 8-bit fallbacks that also "succeed".
        score += 10_000
        score += cjk + latin * 0.5
        return score

    if encoding in {"big5", "cp950"}:
        score += cjk * 4
        score += trad * 8
        score -= simp * 3
        if cjk == 0:
            score -= 30
        else:
            # A successful CJK decode should beat Latin-1 mojibake of the same bytes.
            score += 80
        # Prefer the canonical name big5 when both big5 and cp950 work equally.
        if encoding == "big5":
            score += 0.2
        return score

    if encoding in {"gbk", "gb18030"}:
        score += cjk * 4
        score += simp * 8
        score -= trad * 3
        if cjk == 0:
            score -= 30
        else:
            score += 80
        if encoding == "gbk":
            score += 0.2
        return score

    # latin-1 always decodes; cp1252 usually does. Only a good fit for Western text.
    # A short German/French file has a few accents and many ASCII letters.
    # Mis-decoded CJK usually produces a flood of Latin-1 supplement characters
    # and almost no ASCII letters — penalise that pattern.
    score += min(latin, 8) * 6
    score -= cjk * 5
    if high > ascii_letters:
        score -= (high - ascii_letters) * 8
    if latin == 0 and high:
        score -= 10
    if encoding == "latin-1":
        score += 0.3
    return score


def detect_encoding(data: bytes) -> dict:
    """Return encoding info for a byte string.

    Keys: encoding, bom (bool), bom_kind (str|None), confidence (float).
    """
    if not data:
        return {
            "encoding": "utf-8",
            "bom": False,
            "bom_kind": None,
            "confidence": 1.0,
        }

    bom = sniff_bom(data)
    if bom:
        # Verify the payload actually decodes with the BOM encoding.
        try:
            data.decode(bom)
            return {
                "encoding": bom,
                "bom": True,
                "bom_kind": bom,
                "confidence": 1.0,
            }
        except UnicodeDecodeError:
            pass

    scored: list[tuple[float, int, str]] = []
    for index, enc in enumerate(ENCODING_CANDIDATES):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        scored.append((_score_decoded(text, enc), -index, enc))

    if not scored:
        # Should be unreachable because latin-1 always decodes, but be safe.
        return {
            "encoding": "latin-1",
            "bom": False,
            "bom_kind": None,
            "confidence": 0.1,
        }

    scored.sort(reverse=True)
    best_score, _, best_enc = scored[0]
    families = {
        "utf-8": "utf8",
        "big5": "big5",
        "cp950": "big5",
        "gbk": "gb",
        "gb18030": "gb",
        "cp1252": "latin",
        "latin-1": "latin",
    }
    best_family = families.get(best_enc, best_enc)
    second = None
    for other_score, _, other_enc in scored[1:]:
        if families.get(other_enc, other_enc) != best_family:
            second = other_score
            break
    if second is None or best_score - second > 50:
        confidence = 0.95
    elif best_score - second > 5:
        confidence = 0.8
    else:
        confidence = 0.6
    if best_enc == "utf-8":
        confidence = 1.0

    return {
        "encoding": best_enc,
        "bom": False,
        "bom_kind": None,
        "confidence": confidence,
    }


def decode_bytes(data: bytes, encoding: str | None = None) -> tuple[str, dict]:
    info = detect_encoding(data)
    if encoding:
        info = dict(info)
        info["encoding"] = encoding
        info["overridden"] = True
    text = data.decode(info["encoding"])
    # utf-8-sig decode already strips the BOM from the text.
    return text, info


def classify_line_endings(data: bytes) -> dict:
    """Count CR, LF, and CRLF sequences on the raw bytes (works for 8-bit encodings).

    UTF-16 is handled after decode in a separate path; for typical 8-bit CSV
    this byte-level count is accurate.
    """
    # Avoid double-counting CR and LF that belong to CRLF.
    crlf = data.count(b"\r\n")
    # Temporarily mask CRLF to count lone CR / LF.
    stripped = data.replace(b"\r\n", b"")
    cr = stripped.count(b"\r")
    lf = stripped.count(b"\n")
    kinds: list[str] = []
    if crlf:
        kinds.append("crlf")
    if lf:
        kinds.append("lf")
    if cr:
        kinds.append("cr")
    if not kinds:
        kinds = ["none"]
    return {
        "kinds": kinds,
        "crlf": crlf,
        "lf": lf,
        "cr": cr,
        "mixed": len([k for k in kinds if k != "none"]) > 1,
    }


def _count_unquoted(line: str, delimiter: str) -> int:
    """Count delimiter occurrences that are outside double quotes."""
    count = 0
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                i += 2
                continue
            in_quotes = not in_quotes
            i += 1
            continue
        if ch == delimiter and not in_quotes:
            count += 1
        i += 1
    return count


def _logical_lines(text: str) -> list[str]:
    """Split into logical records, joining quoted newlines when possible."""
    lines: list[str] = []
    buf: list[str] = []
    in_quotes = False
    # Normalize to \n for scanning only; the original line ending report is separate.
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for raw in normalized.split("\n"):
        piece = raw
        # Count whether this piece toggles the quote state.
        i = 0
        toggles = 0
        while i < len(piece):
            if piece[i] == '"':
                if i + 1 < len(piece) and piece[i + 1] == '"':
                    i += 2
                    continue
                toggles += 1
            i += 1
        if in_quotes:
            buf.append("\n" + piece)
        else:
            buf = [piece]
        if toggles % 2 == 1:
            in_quotes = not in_quotes
        if not in_quotes:
            lines.append("".join(buf))
            buf = []
    if buf:
        lines.append("".join(buf))
    # Drop a single trailing empty line caused by a final newline.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def detect_delimiter(text: str, override: str | None = None) -> dict:
    if override is not None:
        return {
            "delimiter": override,
            "name": _delim_name(override),
            "overridden": True,
            "confidence": 1.0,
        }

    delimiters = [",", "\t", ";", "|"]
    lines = [ln for ln in _logical_lines(text) if ln.strip()]
    sample = lines[:40]
    if not sample:
        return {
            "delimiter": ",",
            "name": "comma",
            "overridden": False,
            "confidence": 0.2,
        }

    best: tuple[float, int, str] | None = None
    details: dict[str, dict] = {}
    for index, delim in enumerate(delimiters):
        counts = [_count_unquoted(ln, delim) for ln in sample]
        total = sum(counts)
        field_counts = [c + 1 for c in counts]
        mode, mode_n = Counter(field_counts).most_common(1)[0]
        consistency = mode_n / len(field_counts)
        # A delimiter that never appears is not useful.
        if total == 0:
            score = 0.0
        else:
            score = consistency * 100 + min(mode, 20) + min(total, 50) * 0.1
        details[delim] = {
            "total": total,
            "mode_fields": mode,
            "consistency": consistency,
            "score": score,
        }
        cand = (score, -index, delim)
        if best is None or cand > best:
            best = cand

    assert best is not None
    score, _, delim = best
    if score <= 0:
        return {
            "delimiter": ",",
            "name": "comma",
            "overridden": False,
            "confidence": 0.3,
            "single_column": all(d["total"] == 0 for d in details.values()),
        }
    confidence = 0.95 if score >= 100 else 0.7 if score >= 50 else 0.5
    return {
        "delimiter": delim,
        "name": _delim_name(delim),
        "overridden": False,
        "confidence": confidence,
    }


def _delim_name(delimiter: str) -> str:
    return {
        ",": "comma",
        "\t": "tab",
        ";": "semicolon",
        "|": "pipe",
    }.get(delimiter, "custom")


def iter_unbalanced_quote_lines(text: str) -> Iterable[int]:
    """Yield 1-based physical line numbers with an odd number of unescaped quotes.

    Physical lines are used because a broken quote often first shows up
    as a single line with an unmatched quote character.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for index, line in enumerate(normalized.split("\n"), start=1):
        if _odd_unescaped_quotes(line):
            yield index


def _odd_unescaped_quotes(line: str) -> bool:
    count = 0
    i = 0
    while i < len(line):
        if line[i] == '"':
            if i + 1 < len(line) and line[i + 1] == '"':
                i += 2
                continue
            count += 1
        i += 1
    return count % 2 == 1

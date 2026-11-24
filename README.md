# tabular-lint

tabular-lint is a local, read-only **CSV/TSV linter** for Git repositories and CI, by **Lanternbay Studio**.

It checks tables checked into a project, prints a human report (and optional JSON), and exits with a **nonzero status when error-level issues are found**. It uses the Python 3 standard library only and is licensed under MIT.

It is not a cleaner. For one-off messy exports, see [CSV Clinic](https://csvclinic.itch.io/csv-clinic). See [BUSINESS.md](BUSINESS.md) for how the two products differ.

tabular-lint is published by **Lanternbay Studio**.

## Requirements

- Python 3.9 or newer (`python3 --version`)

## Usage

From a clone of this repository (so the `tabularlint` package is importable), or after `pip install .`:

```bash
python3 -m tabularlint path/to/file.csv
python3 -m tabularlint path/to/repo
python3 -m tabularlint --format json data/
python3 -m tabularlint --format both --json-out report.json data/
```

The same command is available as `tabular-lint` once the package is installed.

Exit codes:

- `0` — no error-level issues (warnings alone do not fail, unless you pass `--strict` or set `"fail_on": "warning"`)
- `1` — at least one error-level issue
- `2` — bad arguments, missing path, or invalid config

## Pre-commit

Add this to your repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/dtpnm857jk-create/tabular-lint
    rev: v0.1.0
    hooks:
      - id: tabular-lint
```

Then run:

```bash
pre-commit install
pre-commit run tabular-lint --all-files
```

The hook is defined at the repository root in [`.pre-commit-hooks.yaml`](.pre-commit-hooks.yaml) (`id: tabular-lint`). The `rev` must be the release tag, currently `v0.1.0`. A copy of this snippet is also in [`examples/pre-commit-config.yaml`](examples/pre-commit-config.yaml).

## GitHub Actions

Copy [`examples/github-workflows/tabular-lint.yml`](examples/github-workflows/tabular-lint.yml) to `.github/workflows/tabular-lint.yml` in your project, or start from this minimal workflow (the job fails when tabular-lint exits 1):

```yaml
name: tabular-lint
on:
  push:
    paths: ["**/*.csv", "**/*.tsv", ".tabularlint.json"]
  pull_request:
    paths: ["**/*.csv", "**/*.tsv", ".tabularlint.json"]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install tabular-lint
        run: pip install git+https://github.com/dtpnm857jk-create/tabular-lint.git@v0.1.0
      - name: Run tabular-lint
        run: tabular-lint .
```

## Config

Optional JSON file named `.tabularlint.json` or `tabularlint.json`, searched from the current directory upward, or passed with `--config`. See [`examples/tabularlint.json`](examples/tabularlint.json).

```json
{
  "include": ["*.csv", "*.tsv"],
  "exclude": [],
  "fail_on": "error",
  "checks": {
    "ragged_row": "error",
    "encoding_non_utf8": "warning",
    "bom": "warning",
    "mixed_line_endings": "warning",
    "mixed_delimiters": "error",
    "duplicate_header": "error",
    "empty_header": "error",
    "trailing_whitespace": "warning"
  }
}
```

Each check is `error`, `warning`, or `off`.

## Checks

| Code | Default | What it flags |
| --- | --- | --- |
| `ragged_row` | error | Data rows whose field count does not match the header |
| `encoding_non_utf8` | warning | File is not UTF-8 (for example Big5 or Latin-1) |
| `bom` | warning | A UTF-8 or UTF-16 byte-order mark at the start of the file |
| `mixed_line_endings` | warning | A mix of CR, LF, and CRLF |
| `mixed_delimiters` | error | More than one delimiter (comma, tab, semicolon, pipe) in active use |
| `duplicate_header` | error | Repeated header names |
| `empty_header` | error | Blank header cells |
| `trailing_whitespace` | warning | Fields that end with a space or tab |

## Verification

```bash
python3 run_fixtures.py
```

A passing run prints `PASS` for each fixture and a final line such as `8 passed, 0 failed, 8 total`. Exit status is 0 only when every fixture passes.

Release archives are published on [Releases](https://github.com/dtpnm857jk-create/tabular-lint/releases).

## Limitations

- One encoding is assumed per file. Detection is a heuristic (no `chardet`).
- Mixed-delimiter detection looks for rows that use a second delimiter and do not contain the primary one. Unusual quoted content can still confuse it.
- The file is loaded into memory. This MVP is aimed at tables in a source repo, not multi-gigabyte dumps.
- This tool reports problems; it does not rewrite files.

## License

MIT. See [LICENSE](LICENSE). Copyright (c) 2026 張閔鈞. Published by **Lanternbay Studio**.

---

## 繁體中文說明

tabular-lint 是給 **Git 倉庫與 CI** 用的 CSV／TSV 巡檢器，由 **Lanternbay Studio** 發布：檢查已提交的表格，輸出人看的報告（也可輸出 JSON），並在發現「錯誤」級問題時以非 0 狀態結束。只用 Python 3 標準庫。它不做清理；清理單份匯出檔請用 [CSV Clinic](https://csvclinic.itch.io/csv-clinic)。差異見 [BUSINESS.md](BUSINESS.md)。

pre-commit（`rev` 請使用發行標籤 `v0.1.0`，hook id 為 `tabular-lint`）：

```yaml
repos:
  - repo: https://github.com/dtpnm857jk-create/tabular-lint
    rev: v0.1.0
    hooks:
      - id: tabular-lint
```

驗證：

```bash
python3 run_fixtures.py
```

## Need a messy CSV fixed?

If you'd rather not fix it yourself: we fix one messy CSV/TSV file for NT$300 (Taiwan), returned within 3 hours with a short change report, and you pay only after you accept the result. Details: [CSV Clinic fix service](https://csvclinic.itch.io/csv-clinic?utm_source=github&utm_medium=readme&utm_campaign=fixservice)



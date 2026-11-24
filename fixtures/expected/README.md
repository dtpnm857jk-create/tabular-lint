# Expected fixture results

Each `fixtures/<stem>.csv` has `<stem>.issues.json`:

- `encoding`, `delimiter`, `bom` must match
- `required` issue codes must appear in the report
- `forbidden` codes must not appear
- `exact` (if present) is the full set of issue codes
- `exit` is the CLI exit code under the default config (`fail_on: error`)

"""``python -m src.parsing``: parse every ABSL file in data/raw (task 1.10).

Writes data/processed/{holdings,totals,schemes}.parquet and
results/parse_report.md. Exit code 1 if any sheet has an ERROR.
"""

from __future__ import annotations

import sys
import time

from src.config import get_settings
from src.parsing.pipeline import parse_files, write_tables
from src.parsing.report import write_report


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    files = sorted(s.paths.raw.glob(s.data.file_glob))
    if not files:
        print(f"No portfolio files matching {s.data.file_glob!r} in {s.paths.raw}")
        return 1
    t0 = time.perf_counter()
    run = parse_files(files)
    written = write_tables(run, s.paths.processed)
    report = write_report(run, s.paths.results / "parse_report.md")

    for f in run.files:
        n = sum(len(x.holdings) for x in f.sheets)
        bad = sum(c.status != "OK" for c in f.checks)
        print(f"{f.as_of_date}  {f.file:48} {len(f.sheets):4} sheets {n:6,} holdings  "
              f"{bad} need attention  {len(f.failed)} failed")
    print(f"\n{len(run.holdings):,} holdings, {len(run.totals):,} total rows, {len(run.schemes)} scheme-months "
          f"in {time.perf_counter() - t0:.1f} s")
    for p in written + [report]:
        print(f"  wrote {p}")
    if run.n_errors:
        print(f"\n{run.n_errors} sheet(s) with errors: see {report.name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

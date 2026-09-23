"""Entry point for the shipment-performance ETL class-project.

Run from this folder with `make run` or `python run.py`. Reads the live
logistics source schema, runs the pipeline, writes the result table into the
learner's own schema, and prints a validation report. Runs the load a second
time and checks the row count is unchanged: the idempotency proof.

Standalone: imports the DB helper from ./vendor/db.py and reads .env from
this folder, so the class-project depends on nothing else in the residency
repository. Copy the folder, drop in a .env, and it runs.
"""

from __future__ import annotations

import json
import pathlib
import sys

# Resolve the folder this file sits in once, up front, so every path in the
# script can be expressed relative to it. Using __file__ rather than the
# current working directory means `python run.py` works regardless of where
# the user is when they run it.
HERE = pathlib.Path(__file__).resolve().parent
# Put this folder at the front of Python's import path so `from vendor.db
# import Database` finds the vendored helper sitting next to run.py.
sys.path.insert(0, str(HERE))
# And add the src directory so `from shipment_etl.pipeline import run`
# resolves without needing the package installed.
sys.path.insert(0, str(HERE / "src"))

# Load .env BEFORE the shipment_etl imports below: those imports pull in
# vendor/db.py, which reads DB_URL at import time. If we loaded the dotenv
# file after that import the engine would already have failed to construct.
# The noqa: E402 acknowledges that "imports at top of file" is being
# deliberately broken here.
from dotenv import load_dotenv             # noqa: E402
load_dotenv(HERE / ".env")

# These imports come after load_dotenv on purpose: shipment_etl and vendor.db
# both read environment variables at import time.
from shipment_etl import RESULT_TABLE      # noqa: E402
from shipment_etl.pipeline import run      # noqa: E402
from vendor.db import Database             # noqa: E402

# Outputs land in ./data/, which the container's docker-compose mounts as a
# volume so the smoke sidecar can read what this script wrote.
DATA_DIR = HERE / "data"
# The quarantine CSV is the human-readable failure record from the validate
# step. Keeping it on disk (not just in memory) lets a reviewer open it and
# inspect specific rows that the pipeline rejected.
QUARANTINE_CSV = DATA_DIR / "quarantine.csv"
# The status JSON is the machine-readable summary the smoke sidecar greps
# against. Format and key names are documented as a contract at the bottom
# of main().
STATUS_JSON = DATA_DIR / "etl_status.json"


def _count_written(db: Database) -> int:
    # Single COUNT(*) on the result table the pipeline just wrote. Double-
    # quoting the schema and table names lets the query handle mixed-case
    # identifiers safely.
    q = f'SELECT COUNT(*) AS n FROM "{db.own_schema}"."{RESULT_TABLE}"'
    # read_sql returns a one-row DataFrame; .iloc[0] picks that first row and
    # int() coerces the numpy int64 to a plain Python int so the caller does
    # not have to care about numpy types downstream.
    return int(db.read_sql(q)["n"].iloc[0])


def main() -> None:
    # exist_ok=True makes this safe to run again and again. The first run
    # creates data/; later runs find it already there and move on.
    DATA_DIR.mkdir(exist_ok=True)
    # Override source_schema to "logistics" because this class-project always
    # reads logistics regardless of the learner's INDUSTRY config. The own
    # schema picks up from the env var the way every other module does.
    db = Database(source_schema="logistics")

    print(f"Source schema: logistics   Your schema: {db.own_schema}\n")
    # One call runs extract, transform, validate, load in order. The pipeline
    # module is where the per-step composition lives; run.py stays an entry
    # point that prints what happened, not where the work happens.
    report = run(db, quarantine_path=QUARANTINE_CSV)

    print("=== Validation report ===")
    print(f"  rows read         : {report['rows_in']:>6}")
    print(f"  quarantined (bad) : {report['quarantined']:>6}")
    print(f"  clean (kept)      : {report['clean']:>6}")
    print("  rejected by rule:")
    # Sort by count descending so the biggest rule failures land at the top
    # of the report. The minus sign in the lambda turns ascending sort into
    # descending without needing the reverse=True flag.
    for reason, n in sorted(report["reason_counts"].items(), key=lambda kv: -kv[1]):
        print(f"    {reason:28} {n:>6}")
    print("\n=== Delivery performance (written rows) ===")
    print(f"  written to {db.own_schema}.{RESULT_TABLE} : {report['written']:>6}")
    print(f"  delivered on time : {report['delivered_on_time']:>6}")
    print(f"  delivered late    : {report['delivered_late']:>6}")
    print(f"  still in progress : {report['in_progress']:>6}")

    # Idempotency proof: count the rows in the result table now, run the
    # pipeline a second time, count again. If the load step is honestly
    # idempotent the two counts match exactly; if it accidentally appends
    # they will not.
    first = _count_written(db)
    # quarantine_path=None on the re-run because we already saved the
    # quarantine CSV; we want the load side effect this time, not another
    # copy of the failure file overwriting the first.
    run(db, quarantine_path=None)
    second = _count_written(db)
    idempotent = first == second
    ok = "OK" if idempotent else "FAILED"
    print("\n=== Idempotency check ===")
    print(f"  rows after run 1: {first}   after run 2: {second}   [{ok}]")
    print(f"\nQuarantined rows saved to {QUARANTINE_CSV.relative_to(HERE)}")

    # The status JSON is the machine-readable contract between this ETL and
    # the docker smoke sidecar. Keep it small and stable: the sidecar greps
    # specific keys, so renaming any of them is a breaking change.
    STATUS_JSON.write_text(
        json.dumps(
            {
                "rows_in": int(report["rows_in"]),
                "quarantined": int(report["quarantined"]),
                "clean": int(report["clean"]),
                "written": int(report["written"]),
                "rows_after_first_load": int(first),
                "rows_after_second_load": int(second),
                "idempotent": bool(idempotent),
            },
            indent=2,
        )
    )
    print(f"Status written to {STATUS_JSON.relative_to(HERE)}")

    # Exit non-zero if the idempotency check failed. The container's smoke
    # sidecar uses this exit code to fail the compose run, which is what
    # turns "the pipeline ran" into "the pipeline ran correctly" at the CI
    # boundary.
    if not idempotent:
        sys.exit(1)


if __name__ == "__main__":
    main()

"""The orchestrator: wire the four steps into one run.

`run` performs extract, validate, transform, load in order, saves the quarantined
rows to a CSV for inspection, and returns a small report dict describing what
happened. Keeping the report as data (not just printed text) means the caller,
including the tests, can check the numbers.
"""

from __future__ import annotations

import pathlib

import pandas as pd

from .extract import extract
from .validate import validate
from .transform import transform
from .load import load


def run(db, quarantine_path: pathlib.Path | str | None = None) -> dict:
    """Run the full pipeline and return a report of what it did."""
    # Each step is a plain function returning DataFrames, so the orchestrator
    # is just three named handoffs. That layout makes each step independently
    # testable; this run() function is mostly composition, not logic.
    shipments, events = extract(db)
    clean, quarantine = validate(shipments)
    performance = transform(clean, events)

    # Persist the rejected rows with their reasons, so the decision is auditable.
    # quarantine_path=None is the second-run case from run.py's idempotency
    # check: we still want the load side effect, but we already saved the
    # quarantine CSV on the first call and do not want to overwrite it.
    if quarantine_path is not None:
        quarantine.to_csv(quarantine_path, index=False)

    # Load is last so a validate or transform error halts the run before any
    # write touches your schema. That ordering is the small safety net for
    # "do not partially commit a broken result".
    load(db, performance, rows_in=len(shipments), rows_dropped=len(quarantine))

    # Slice to delivered rows once so the two on_time counts below can read
    # from the same frame. .delivery_class is what transform() set; using it
    # here keeps the report consistent with the table the load step wrote.
    delivered = performance[performance["delivery_class"] == "delivered"]
    report = {
        "rows_in": int(len(shipments)),
        "quarantined": int(len(quarantine)),
        "clean": int(len(clean)),
        "written": int(len(performance)),
        # == True / == False on a nullable boolean column is intentional here:
        # we want to count delivered shipments where the value is exactly True
        # or exactly False, treating NA as neither. The noqa: E712 silences
        # flake8's usual "compare with `is`" rule because `is` does not work
        # on pandas NA-bearing booleans.
        "delivered_on_time": int((delivered["on_time"] == True).sum()),   # noqa: E712
        "delivered_late": int((delivered["on_time"] == False).sum()),     # noqa: E712
        "in_progress": int((performance["delivery_class"] == "in_progress").sum()),
        "reason_counts": _reason_counts(quarantine),
    }
    return report


def _reason_counts(quarantine: pd.DataFrame) -> dict:
    """Count how many rows hit each individual rule (a row can hit several)."""
    # Empty quarantine is a real case: a clean source dataset has no rejected
    # rows. Returning an empty dict instead of erroring keeps the report shape
    # stable so the caller can sort it without a special case.
    if quarantine.empty:
        return {}
    # Split the comma-separated reasons on each row, explode so each reason
    # becomes its own row, then strip whitespace. The result is one reason per
    # row, ready to count, even when a single shipment broke multiple rules.
    exploded = (
        quarantine["quarantine_reasons"].str.split(",").explode().str.strip()
    )
    # value_counts gives a Series of (reason -> count). .to_dict() hands it
    # back as a plain dict so the report stays JSON-serialisable for the
    # docker smoke sidecar.
    return exploded.value_counts().to_dict()

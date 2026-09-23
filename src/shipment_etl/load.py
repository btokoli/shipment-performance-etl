"""Step 4: load.

Loading writes the transformed table into your own schema. The one habit that
matters most here is idempotency: running the pipeline twice must leave the same
result, not two stacked copies. The shared Database.write_own does this by
replacing the table on each run, so the load is safe to repeat. We also append a
row to the etl_runs audit log so every run leaves an honest trace of what it did.
"""

from __future__ import annotations

import pandas as pd

from . import PIPELINE_NAME, RESULT_TABLE


def load(db, performance: pd.DataFrame, rows_in: int, rows_dropped: int) -> None:
    """Write the performance table to your schema and log the run.

    write_own replaces the table, so calling load again with the same data
    produces the same single table, never a duplicate. That is what makes the
    whole pipeline safe to re-run, which pipelines always end up being.
    """
    # write_own's default if_exists="replace" is what gives this pipeline its
    # idempotency. The trailing comment is preserved here as a reminder for
    # anyone scanning the file that the choice of "replace" is the load
    # contract, not an accident.
    db.write_own(performance, RESULT_TABLE)  # if_exists="replace" -> idempotent
    # log_run appends one row to the etl_runs table in your own schema. It is
    # append-only on purpose: the run history is meant to grow, so a future
    # reader can answer "when did this pipeline last run, and how many rows
    # did it move?" by reading a single table.
    db.log_run(
        pipeline=PIPELINE_NAME,
        rows_in=rows_in,
        rows_out=len(performance),
        rows_dropped=rows_dropped,
        note=f"wrote {RESULT_TABLE}",
    )

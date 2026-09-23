"""Step 1: extract.

Extraction is the easy step to underrate. All it does is pull the raw source
tables into memory so the later steps can work on them. We read the two tables
this pipeline needs, shipments and the delivery events that track each one, and
we read them through the shared Database wrapper so the read stays inside the
read-only source schema. Nothing here changes the source.
"""

from __future__ import annotations

import pandas as pd


def extract(db) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read the two source tables and return them as (shipments, events).

    `db` is a Database (vendored at ./vendor/db.py) pointed at the logistics
    source schema. We read whole tables here because this dataset is small
    enough to fit comfortably in memory; at larger scale you would extract
    in date-bounded batches instead.
    """
    # read_source goes through the vendored Database helper, which builds the
    # SELECT with the source_schema baked in. That keeps the read inside the
    # read-only logistics schema and away from any other learner's namespace.
    shipments = db.read_source("shipments")
    # Same helper for the second table. Two reads here keep the rest of the
    # pipeline pure: transform and validate never touch the database again.
    events = db.read_source("delivery_events")
    return shipments, events

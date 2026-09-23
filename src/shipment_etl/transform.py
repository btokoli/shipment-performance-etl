"""Step 3: transform.

Transformation turns clean source rows into the columns the business actually
wants. Here that means delivery performance: how long each shipment took, whether
it arrived on time, and where it last was. We also fold in the single most recent
delivery event per shipment, which is a small grouped join, the kind of work that
belongs in the pipeline rather than in every query that reads the result later.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# The shape of the table this pipeline produces. Fixing the output columns keeps
# the result stable: re-running the pipeline always writes the same schema.
OUTPUT_COLUMNS = [
    "shipment_id", "tracking_number", "destination_city", "destination_country",
    "category", "priority", "weight_kg", "status", "delivery_class",
    "shipped_date", "estimated_delivery", "actual_delivery",
    "transit_days", "on_time", "last_event_type", "last_location",
    "shipping_cost", "is_insured",
]


def _latest_events(events: pd.DataFrame) -> pd.DataFrame:
    """Return one row per shipment: its most recent delivery event.

    Events are ordered by date then time (the time column is a HH:MM string,
    which sorts correctly as text), and we keep the last one for each shipment.
    """
    ev = events.copy()
    # Coerce event_date to a real datetime; bad strings become NaT, which sorts
    # to the end of an ascending sort and so cannot accidentally win the
    # "latest event" position for a shipment.
    ev["event_date"] = pd.to_datetime(ev["event_date"], errors="coerce")
    # Fill missing event_time with "" so the sort is stable instead of putting
    # NaN-bearing rows in an unpredictable spot. HH:MM strings sort the same
    # as the underlying numbers, so no real datetime parse is needed.
    ev["event_time"] = ev["event_time"].fillna("")
    # Sort ascending so groupby...tail(1) below picks the most recent event in
    # each shipment's group; "most recent" is well-defined because we just
    # locked the sort.
    ev = ev.sort_values(["shipment_id", "event_date", "event_time"])
    # tail(1) per group is the idiomatic pandas way to pick the last row of
    # each group after sorting. as_index=False keeps shipment_id as a column
    # so the downstream merge can use it.
    latest = ev.groupby("shipment_id", as_index=False).tail(1)
    # Rename to the column names the output schema uses, so the merge in
    # transform() lands on the right column without further wrangling.
    return latest[["shipment_id", "event_type", "location"]].rename(
        columns={"event_type": "last_event_type", "location": "last_location"}
    )


def transform(clean: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Build the per-shipment performance table from clean shipments and events."""
    df = clean.copy()

    # Reusable mask: shipments that have arrived. Several columns below depend
    # on it, so naming it once keeps the intent visible at each use site.
    delivered = df["status"] == "Delivered"

    # Transit time, in whole days, only defined where the shipment has arrived.
    # For shipments still moving, actual_delivery is missing, so this is NaT minus
    # a date, which becomes a missing value: the honest "not known yet".
    df["transit_days"] = (df["actual_delivery"] - df["shipped_date"]).dt.days
    # Int64 is pandas' nullable integer type. A plain int column would refuse
    # to hold NaN; Int64 lets in-progress shipments stay missing in the same
    # column rather than being silently turned into a number.
    df["transit_days"] = df["transit_days"].astype("Int64")

    # On-time is only meaningful for delivered shipments. We use pandas' nullable
    # boolean so in-progress shipments are a clean missing value, not a guessed
    # False. A nullable boolean also writes cleanly back to the database.
    on_time = (df["actual_delivery"] <= df["estimated_delivery"])
    # .where keeps the original value where the condition is True and replaces
    # it with the `other` value (pd.NA here) everywhere else. So in-progress
    # rows become NA in the on_time column rather than carrying a misleading
    # True/False derived from missing data.
    df["on_time"] = on_time.where(delivered, other=pd.NA).astype("boolean")

    # A simple class so the result is easy to filter without re-deriving status.
    # np.where is the vectorised if-else: True positions get "delivered",
    # False positions get "in_progress", all in one pass over the column.
    df["delivery_class"] = np.where(delivered, "delivered", "in_progress")

    # Left-join the latest event onto each shipment. Left so a shipment with
    # no events still appears (with NaN in the event columns) rather than
    # disappearing from the result.
    out = df.merge(_latest_events(events), on="shipment_id", how="left")
    # Project to the fixed output schema declared at the top of the file. This
    # is what keeps the load step's CREATE TABLE shape stable across runs.
    return out[OUTPUT_COLUMNS]

"""Step 2: validate.

This is the heart of the project. Real source data has problems, and the job of
validation is not to silently drop the bad rows but to separate them from the
good ones and record exactly why each was rejected. That record is what lets a
data engineer answer "what did the pipeline throw away, and was it right to?"
the next morning, instead of guessing.

The pattern here is quarantine-and-report: every row that fails at least one rule
is moved to a quarantine table with a human-readable reason, and only the rows
that pass every rule continue down the pipeline.
"""

from __future__ import annotations

import pandas as pd

from . import KNOWN_STATUSES

# The columns we treat as dates and as numbers. We coerce them up front so a
# stray string or empty value becomes a missing value we can test for, rather
# than blowing up a comparison later.
_DATE_COLS = ("shipped_date", "estimated_delivery", "actual_delivery")


def _coerce_types(shipments: pd.DataFrame) -> pd.DataFrame:
    # Copy first so the caller's DataFrame is never mutated. Surprising
    # behaviour from an in-place change is one of the loudest pandas
    # complaints, and a one-line .copy() avoids it for good.
    df = shipments.copy()
    for col in _DATE_COLS:
        # errors="coerce" converts unparseable values to NaT instead of
        # raising. That is what turns "bad input" into "missing input" so
        # the isna() check in the rules below can catch it.
        df[col] = pd.to_datetime(df[col], errors="coerce")
    # Same idea for weight: a stray string becomes NaN, which the bad_weight
    # rule below picks up.
    df["weight_kg"] = pd.to_numeric(df["weight_kg"], errors="coerce")
    return df


def validate(shipments: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split shipments into (clean, quarantine).

    The quarantine frame carries an extra `quarantine_reasons` column listing
    every rule a row broke, comma-separated. A row appears in exactly one of the
    two frames, never both, so clean + quarantine always equals the input count.
    """
    df = _coerce_types(shipments)

    # Start every row with no reasons, then append a label wherever a rule fails.
    reasons = pd.Series([""] * len(df), index=df.index)

    def flag(mask: pd.Series, label: str) -> None:
        # Append `label` to the reason string of each row the mask selects.
        # fillna(False) handles masks that come back with NaN from comparisons
        # against missing values; without it, an NaN mask raises rather than
        # cleanly selecting no rows. Worked example: when weight_kg is NULL,
        # weight_kg <= 0 returns NaN, and fillna(False) says an unknown
        # weight is not a confirmed violation.
        sel = mask.fillna(False)
        # The lambda joins the new label to whatever was already there, with a
        # comma only when there's something to join to. That builds up the
        # multi-rule reason strings ("bad_weight,delivered_without_date")
        # without a stray leading or trailing comma.
        reasons.loc[sel] = reasons.loc[sel].map(
            lambda existing: f"{existing},{label}" if existing else label
        )

    # Rule 1: a shipment with no ship date cannot be reasoned about at all.
    flag(df["shipped_date"].isna(), "missing_shipped_date")

    # Rule 2: weight must be a positive number. Null, zero, or negative is bad
    # data. The combined mask catches all three classes of failure as the
    # single rule the analyst will think of in one piece.
    flag(df["weight_kg"].isna() | (df["weight_kg"] <= 0), "bad_weight")

    # Rule 3: a delivery cannot happen before the shipment left. Impossible
    # timeline. The notna guards keep the comparison sane on rows where one
    # of the two dates is missing, so this rule only fires when both are
    # present and the timeline is actually impossible.
    flag(
        df["actual_delivery"].notna()
        & df["shipped_date"].notna()
        & (df["actual_delivery"] < df["shipped_date"]),
        "delivery_before_shipment",
    )

    # Rule 4: the estimate cannot predate the ship date either. Same notna
    # guards as rule 3, same shape, different pair of columns.
    flag(
        df["estimated_delivery"].notna()
        & df["shipped_date"].notna()
        & (df["estimated_delivery"] < df["shipped_date"]),
        "estimate_before_shipment",
    )

    # Rule 5: the status must be one we recognise. This guards against new or
    # corrupted status values. On today's data it flags nothing, which is the
    # honest result: the rule earns its place the day a bad status appears.
    flag(~df["status"].isin(KNOWN_STATUSES), "unknown_status")

    # Rule 6: a shipment marked Delivered must have an actual delivery date. A
    # missing one means the record contradicts itself.
    flag(
        (df["status"] == "Delivered") & df["actual_delivery"].isna(),
        "delivered_without_date",
    )

    # A row is bad if any rule fired, which equals "the reasons string is not
    # empty". The two .copy() calls below decouple clean and quarantine from
    # the input df so downstream mutations cannot leak across.
    is_bad = reasons != ""
    clean = df[~is_bad].copy()
    quarantine = df[is_bad].copy()
    # Attach the reasons string only to the quarantine frame so a reviewer
    # opening the CSV can read exactly which rule (or rules) caught each row.
    quarantine["quarantine_reasons"] = reasons[is_bad]
    return clean, quarantine

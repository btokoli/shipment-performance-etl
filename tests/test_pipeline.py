"""Unit tests for validate and transform.

These run on tiny hand-built DataFrames with no database, so they are fast and
deterministic and pin down the exact behaviour of the rules and the metrics. The
extract and load steps are thin database wrappers and are exercised live by the
instructor demo, not mocked here.
"""

import pandas as pd

from shipment_etl.validate import validate
from shipment_etl.transform import transform


def _shipment(**over):
    """A valid baseline shipment row; override fields to make it break a rule."""
    base = dict(
        shipment_id=1, tracking_number="TRK1", origin_warehouse=1,
        destination_city="Lagos", destination_country="NG", driver_id=1,
        vehicle_id=1, weight_kg=10.0, category="standard", priority="normal",
        shipped_date="2026-01-01", estimated_delivery="2026-01-05",
        actual_delivery="2026-01-04", status="Delivered",
        shipping_cost=50.0, is_insured=True,
    )
    base.update(over)
    return base


def test_clean_row_passes():
    df = pd.DataFrame([_shipment()])
    clean, quarantine = validate(df)
    assert len(clean) == 1
    assert len(quarantine) == 0


def test_each_rule_quarantines_with_reason():
    rows = [
        _shipment(shipment_id=1, shipped_date=None),                       # missing_shipped_date
        _shipment(shipment_id=2, weight_kg=0),                             # bad_weight
        _shipment(shipment_id=3, weight_kg=-4),                            # bad_weight
        _shipment(shipment_id=4, actual_delivery="2025-12-30"),           # delivery_before_shipment
        _shipment(shipment_id=5, estimated_delivery="2025-12-30"),        # estimate_before_shipment
        _shipment(shipment_id=6, status="Teleported"),                    # unknown_status
        _shipment(shipment_id=7, status="Delivered", actual_delivery=None),  # delivered_without_date
    ]
    clean, quarantine = validate(pd.DataFrame(rows))
    assert len(clean) == 0
    assert len(quarantine) == 7
    reasons = dict(zip(quarantine["shipment_id"], quarantine["quarantine_reasons"]))
    assert reasons[1] == "missing_shipped_date"
    assert reasons[2] == "bad_weight" and reasons[3] == "bad_weight"
    assert reasons[4] == "delivery_before_shipment"
    assert reasons[5] == "estimate_before_shipment"
    assert reasons[6] == "unknown_status"
    assert reasons[7] == "delivered_without_date"


def test_clean_plus_quarantine_equals_input():
    rows = [_shipment(shipment_id=1), _shipment(shipment_id=2, weight_kg=None)]
    clean, quarantine = validate(pd.DataFrame(rows))
    assert len(clean) + len(quarantine) == 2


def test_transform_metrics():
    clean = pd.DataFrame([
        _shipment(shipment_id=1, shipped_date="2026-01-01",
                  estimated_delivery="2026-01-05", actual_delivery="2026-01-04",
                  status="Delivered"),                                   # on time, 3 days
        _shipment(shipment_id=2, shipped_date="2026-01-01",
                  estimated_delivery="2026-01-05", actual_delivery="2026-01-09",
                  status="Delivered"),                                   # late, 8 days
        _shipment(shipment_id=3, status="In Transit", actual_delivery=None),  # in progress
    ])
    clean, _ = validate(clean)
    events = pd.DataFrame([
        {"shipment_id": 1, "event_date": "2026-01-02", "event_time": "09:00",
         "event_type": "Picked Up", "location": "Lagos"},
        {"shipment_id": 1, "event_date": "2026-01-04", "event_time": "16:00",
         "event_type": "Delivered", "location": "Abuja"},
    ])
    out = transform(clean, events).set_index("shipment_id")
    assert out.loc[1, "transit_days"] == 3
    assert out.loc[2, "transit_days"] == 8
    assert out.loc[1, "on_time"] == True            # noqa: E712
    assert out.loc[2, "on_time"] == False           # noqa: E712
    assert pd.isna(out.loc[3, "on_time"])           # in progress -> unknown
    assert out.loc[3, "delivery_class"] == "in_progress"
    # latest event for shipment 1 is the later-timestamped Delivered in Abuja
    assert out.loc[1, "last_event_type"] == "Delivered"
    assert out.loc[1, "last_location"] == "Abuja"

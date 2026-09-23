"""shipment_etl: a small, honest ETL pipeline over the logistics shipments data.

The pipeline has four steps, one module each, in the order data moves:

    extract  -> read shipments and delivery_events from the source schema
    validate -> split clean rows from bad rows, recording WHY each was rejected
    transform-> turn clean rows into per-shipment delivery metrics
    load     -> write the result into your own schema, safely re-runnable

`pipeline.run` wires the four together. Each step is a plain function so you can
read it, test it, and reuse it on its own.
"""

KNOWN_STATUSES = {"Delivered", "Delayed", "In Transit", "Returned", "Out for Delivery"}
RESULT_TABLE = "shipment_performance"
PIPELINE_NAME = "shipment_performance_etl"

# Class-project: Shipment performance ETL

A small, complete ETL pipeline that turns raw logistics shipment records into a
clean delivery-performance table. It is the Module 05 ideas (extract, validate,
transform, load) applied end to end to a real dataset, with the focus on the
part that matters most in practice: separating bad rows from good ones and
recording why each was rejected.

This is a self-contained class-project. Copying this folder to an empty
directory and running install + run + docker works. The DB helper is vendored
under `vendor/db.py` so the folder has no external repo dependencies.

## What it does

Reads two source tables from the `logistics` schema, `shipments` and
`delivery_events`, then:

1. **Validates** every shipment against six rules and splits the rows into a
   clean set and a quarantine set, where each quarantined row carries the exact
   reasons it failed.
2. **Transforms** the clean rows into delivery metrics: transit days, an on-time
   flag, a delivered/in-progress class, and the most recent delivery event.
3. **Loads** the result into a `shipment_performance` table in the learner's own
   schema, and appends a row to `etl_runs` audit log.

The load replaces the table on each run, so running the pipeline twice produces
the same single table, never duplicates. `run.py` proves this by loading twice
and checking the row count is unchanged, then writes a status JSON the docker
smoke sidecar reads to grade the run.

## The validation rules

A row is quarantined if it breaks any of these:

| Rule | Reason label |
|------|--------------|
| No ship date | `missing_shipped_date` |
| Weight null, zero, or negative | `bad_weight` |
| Delivered before it shipped | `delivery_before_shipment` |
| Estimated delivery before it shipped | `estimate_before_shipment` |
| Status not in the known set | `unknown_status` |
| Marked Delivered but no actual date | `delivered_without_date` |

On the current data, three of these fire. The other three find nothing today;
they are there to catch the bad data that has not arrived yet, which is the
honest reason most validation rules exist.

## Layout

```
class-project/
├── README.md
├── RUNBOOK.md             runbook for the live session
├── Dockerfile
├── docker-compose.yml
├── Makefile
├── requirements.txt
├── .env.example
├── run.py                          entry point: runs pipeline + idempotency check
├── vendor/
│   ├── __init__.py
│   └── db.py                       vendored Database helper (zero external deps)
├── src/shipment_etl/
│   ├── __init__.py                 shared constants
│   ├── extract.py                  step 1: read the source tables
│   ├── validate.py                 step 2: split clean from quarantine
│   ├── transform.py                step 3: compute the delivery metrics
│   ├── load.py                     step 4: write to learner schema, idempotently
│   └── pipeline.py                 wire the four steps together
├── tests/
│   ├── conftest.py
│   └── test_pipeline.py            unit tests for validate and transform, no DB
└── data/                           quarantine.csv and etl_status.json land here
                                     (gitignored)
```

## Running it

### From this folder (host)

```
pip install -r requirements.txt   # or: make install
cp .env.example .env              # then fill in DB_URL
make run                          # or: python run.py
make test                         # or: python -m pytest -q
```

`make test` needs no database: the tests run on small in-memory tables.
`make run` reads the live `logistics` data and writes
`shipment_performance` into the learner's own schema.

### In Docker (the live session demo)

```
make up                # docker compose up: etl + smoke; smoke asserts on the status JSON
make down              # tear down + remove the etl-data volume
```

The `etl` container runs the pipeline once and exits 0 on success. The
`smoke` sidecar waits for completion (via `service_completed_successfully`),
reads `data/etl_status.json` from the shared volume, asserts
`written > 0` AND `idempotent == true`, and prints `SMOKE-OK`. If either
assertion breaks the compose run fails non-zero. `make up` is the
single-command "did the ETL work end to end" check the cohort sees in the
live session.

## What you should see

About 40,000 shipments read, around 3,000 quarantined (most for bad weight, the
rest for an impossible timeline or a Delivered status with no date), and the
remaining clean rows written as the performance table. The idempotency check at
the end reports the same row count after both loads. The smoke sidecar reads
those same numbers and confirms `SMOKE-OK`.

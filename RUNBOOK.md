# Runbook: Shipment performance ETL

Teaching script for the Module 05 class-project. The runbook for both
instructors leading the live build and self-directed learners running it solo.
It tells you how to prepare, how to walk the build, the exact live run to do
in front of the cohort, and the gotchas to head off. Time estimate: 45 to 60
minutes.

## What this teaches

The lesson and drills in Module 05 already show extract, transform, and load on
the bootcamp data. This project moves the focus to the step engineers actually
spend their time on: validation, and specifically the quarantine-and-report
pattern. The point you want to land is that good pipelines do not silently drop
bad rows; they set them aside with a reason, so the decision is auditable. The
second point is idempotency: a pipeline you cannot safely re-run is a liability.

## Pre-class prep (do this before the cohort arrives)

1. The class-project is standalone: cd into this folder, install deps,
   put a `.env` here with `DB_URL`, and the pipeline runs without any
   reference to the residency repo root.
   ```bash
   pip install -r requirements.txt        # or: make install
   cp .env.example .env                    # then fill in DB_URL
   python run.py                           # confirm it lands clean
   ```
2. The vendored helper at `vendor/db.py` reads `LEARNER_SCHEMA` from the
   environment (default `my_work`). Set it in your `.env` if you want
   the demo to write somewhere else.
3. Do one dry run of the live demo yourself (below) so there are no
   surprises on the projector. Then drop the demo table so the cohort
   sees it created live:
   ```bash
   python -c "import sys; sys.path.insert(0, '.'); from dotenv import load_dotenv; load_dotenv('.env'); \
   from vendor.db import Database; from sqlalchemy import text; d=Database(); \
   c=d.engine.connect(); c.execute(text(f'DROP TABLE IF EXISTS \"{d.own_schema}\".shipment_performance')); c.commit()"
   ```
4. Have the validation-rules table from the README on screen to refer to.

## Walkthrough script (build the understanding)

Open the four step files in data-flow order and narrate each in a sentence or
two. Keep it to the shape, not line-by-line:

- `extract.py`: reads the two source tables through the vendored Database
  wrapper at `vendor/db.py`, which keeps the read inside the read-only source
  schema. Make the point that extraction is deliberately boring.
- `validate.py`: the centre of the project. Walk the six rules. Stress that a row
  failing any rule goes to quarantine with its reasons, and that clean plus
  quarantine always equals the input, nothing vanishes.
- `transform.py`: clean rows become metrics. Point out `on_time` is a nullable
  boolean, so a shipment still in transit is an honest "unknown", not a guessed
  False. This is a good moment to discuss why a missing value is a value.
- `load.py`: writes with replace, which is what makes the run idempotent, and
  logs the run to `etl_runs`.

Then run the tests so they see the rules pinned down without a database:
```bash
make test        # or: python -m pytest -q     -> 4 passed
```

## LIVE DEMO (the teaching moment, run against the live database)

This is the part the cohort is here for. Run the real pipeline against the live
`logistics` data on the projector.

Command (from the `class-project` folder):
```bash
python run.py
```

Expected output (verified against the live database on 2026-05-27; the shipment
counts are stable, so these numbers should match closely):
```
Source schema: logistics   Your schema: my_work

=== Validation report ===
  rows read         :  40005
  quarantined (bad) :   3037
  clean (kept)      :  36968
  rejected by rule:
    bad_weight                     2002
    delivered_without_date          756
    delivery_before_shipment        331

=== Delivery performance (written rows) ===
  written to my_work.shipment_performance :  36968
  delivered on time :   2597
  delivered late    :   4344
  still in progress :  30027

=== Idempotency check ===
  rows after run 1: 36968   after run 2: 36968   [OK]
```

Talking points while it runs:

- Pause on the rejected-by-rule breakdown. Ask the cohort which rule they expected
  to fire most. The big one is `bad_weight` (2,002 rows): null, zero, or negative
  weights are the most common real defect here. `delivered_without_date` (756) is
  the interesting one, a record that contradicts itself by being marked Delivered
  with no delivery date.
- Note that three of the six rules flagged nothing today. Say plainly that this is
  the honest result: those rules guard against bad data that has not arrived yet,
  and a rule firing zero times is not a wasted rule.
- The on-time picture is worth a beat: of the delivered shipments, more are late
  (4,344) than on time (2,597). That is a real finding in the data, not a bug.
- Land the idempotency check: the table has the same row count after both loads.
  Re-running did not duplicate anything. That is what "safe to re-run" means.

Then show the quarantine file so the rejection is concrete, not abstract:
```bash
python -c "import pandas as pd; q=pd.read_csv('data/quarantine.csv'); \
print(q[['shipment_id','status','weight_kg','quarantine_reasons']].head(10).to_string(index=False))"
```

Optionally, show the written table directly so they see real output in the
database, not just a printout:
```bash
python -c "import sys; sys.path.insert(0, '.'); from dotenv import load_dotenv; load_dotenv('.env'); \
from vendor.db import Database; d=Database(); \
print(d.read_sql(f'SELECT shipment_id, destination_city, transit_days, on_time, last_event_type FROM \"{d.own_schema}\".shipment_performance LIMIT 8').to_string(index=False))"
```

## LIVE DEMO (the docker version, run in the live session after the host run)

The pipeline also ships with a docker compose stack that exercises the same
flow inside a container and grades the run with a smoke sidecar. Run it as
the second half of the live demo so the cohort sees the same numbers come
out of the container that came out of the host:

```bash
make up                # or: docker compose up --build --abort-on-container-exit --exit-code-from smoke
```

Verified output (2026-05-28):

```
shipment-etl       | === Idempotency check ===
shipment-etl       |   rows after run 1: 36968   after run 2: 36968   [OK]
shipment-etl       | Status written to data/etl_status.json
shipment-etl exited with code 0
shipment-etl-smoke | === etl_status.json (full) =============================
shipment-etl-smoke | {
shipment-etl-smoke |   "rows_in": 40005,
shipment-etl-smoke |   "quarantined": 3037,
shipment-etl-smoke |   "clean": 36968,
shipment-etl-smoke |   "written": 36968,
shipment-etl-smoke |   "rows_after_first_load": 36968,
shipment-etl-smoke |   "rows_after_second_load": 36968,
shipment-etl-smoke |   "idempotent": true
shipment-etl-smoke | }
shipment-etl-smoke | === assertions =========================================
shipment-etl-smoke | rows_in=40005  quarantined=3037  written=36968
shipment-etl-smoke | idempotency: 36968 == 36968
shipment-etl-smoke | SMOKE-OK
shipment-etl-smoke exited with code 0
```

What to point at:

- The etl container runs the SAME `python run.py` the host ran, against
  the SAME database, and writes its status JSON to a shared named volume
  (`etl-data`).
- The smoke sidecar starts only after the etl container exits cleanly
  (`depends_on: service_completed_successfully`), reads the status JSON,
  and asserts on three things: `written > 0`, `idempotent == true`, and
  `rows_after_first_load == rows_after_second_load`. If any assertion
  fails the smoke exits non-zero and the whole compose run fails. This
  is the production discipline: a green compose run is a verified
  pipeline, not a hopeful one.
- Tear down with `make down`. The `-v` flag also removes the named
  volume so the next run starts clean.

## Standalone-extract property

This class-project is standalone-repo compliant. Copy the folder to an
empty directory, drop in your own `.env`, and run the same recipe. The
DB helper is vendored under `vendor/db.py`; there are no imports from
the residency repo root. Verified on 2026-05-28 by copying to
`/tmp/m05cp-extract/`, installing requirements, running tests (4/4
pass), running the host pipeline (identical 40,005 / 3,037 / 36,968
numbers), and running docker compose (identical scorecard, SMOKE-OK,
exit 0).

## Gotchas to watch for in front of the cohort

- **No `.env` / connection error.** If `run.py` cannot connect, the class-project
  folder's `.env` is missing or `DB_URL` is wrong. (The pipeline reads from
  THIS folder's `.env`, not the repo root, since the standalone retrofit.)
  Fix it before class with a quick `python run.py` that lands clean; do not
  debug it live.
- **`make` not installed (Windows).** Run `python run.py` and `python -m pytest -q`
  directly. The Makefile is a convenience, not a requirement.
- **Wrong schema.** If `LEARNER_SCHEMA` points at a shared or protected schema,
  the write will fail or land in the wrong place. Confirm it is your scratch
  schema in prep step 2.
- **"The numbers moved slightly."** If the seed data was refreshed the counts can
  shift a little. Treat the printed numbers as the source of truth and update the
  expected block above if they drift; do not claim a number you did not just see.
- **Someone asks why late beats on-time.** It is genuine in the source data. Resist
  inventing a cause; the honest answer is that this dataset has more late than
  on-time delivered shipments, and investigating why would be a follow-on analysis.

## Discussion prompts

- We quarantined rows instead of deleting them. Who needs that quarantine table
  the next morning, and what question does it answer?
- The `unknown_status` rule caught nothing today. Should we keep it? (Yes: it is
  cheap insurance, and the day a bad status appears you want it caught, not loaded.)
- The load replaces the table. When would `append` be the right choice instead,
  and what breaks if you pick wrong?
- `on_time` is null for in-progress shipments. What would go wrong if we had
  defaulted it to False?

## Cleanup after class

The output table is the learner's deliverable, so leave it if you want them to
inspect it. To reset for the next cohort, drop it (uses the vendored helper):
```bash
python -c "import sys; sys.path.insert(0, '.'); from dotenv import load_dotenv; load_dotenv('.env'); \
from vendor.db import Database; from sqlalchemy import text; d=Database(); \
c=d.engine.connect(); c.execute(text(f'DROP TABLE IF EXISTS \"{d.own_schema}\".shipment_performance')); \
c.execute(text(f'DROP TABLE IF EXISTS \"{d.own_schema}\".etl_runs')); c.commit()"
```

Also tear down any docker state from the live session:
```bash
make down               # docker compose down -v (also removes the etl-data volume)
```

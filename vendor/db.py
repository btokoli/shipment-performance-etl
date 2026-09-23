"""Minimal vendored Database helper for the Module 05 class-project.

Subset of darko_data.Database inlined so the folder is standalone. Only the
methods this class-project actually uses are vendored: read_source,
read_sql, ensure_own_schema, write_own, and log_run (the audit row the ETL
appends to etl_runs).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("shipment-etl")


def _make_engine() -> Engine:
    url = os.environ.get("DB_URL")
    if not url:
        raise EnvironmentError(
            "DB_URL is not set. Put DB_URL=postgresql://user:pass@host:5432/db "
            "in a .env file in this folder, or export it in your shell."
        )
    return create_engine(url, pool_pre_ping=True)


class Database:
    def __init__(
        self,
        engine: Optional[Engine] = None,
        source_schema: Optional[str] = None,
        own_schema: Optional[str] = None,
    ) -> None:
        self.engine = engine or _make_engine()
        self.source_schema = source_schema or os.environ.get("INDUSTRY", "logistics")
        self.own_schema = own_schema or os.environ.get("LEARNER_SCHEMA", "my_work")
        self.log = log

    def read_source(self, table: str, limit: Optional[int] = None) -> pd.DataFrame:
        sql = f'SELECT * FROM "{self.source_schema}"."{table}"'
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        with self.engine.connect() as conn:
            df = pd.read_sql(text(sql), conn)
        log.info(f"Read {len(df)} rows from {self.source_schema}.{table}")
        return df

    def read_sql(self, query: str) -> pd.DataFrame:
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn)

    def ensure_own_schema(self) -> None:
        with self.engine.connect() as conn:
            found = conn.execute(
                text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"),
                {"s": self.own_schema},
            ).fetchone()
        if found:
            return
        with self.engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self.own_schema}"'))
        log.info(f"Created schema {self.own_schema}")

    def write_own(self, df: pd.DataFrame, table: str, if_exists: str = "replace") -> None:
        self.ensure_own_schema()
        df.to_sql(
            table, self.engine, schema=self.own_schema, if_exists=if_exists, index=False
        )
        log.info(
            f"Wrote {len(df)} rows to {self.own_schema}.{table} (if_exists={if_exists})"
        )

    def log_run(
        self,
        pipeline: str,
        rows_in: int,
        rows_out: int,
        rows_repaired: int = 0,
        rows_dropped: int = 0,
        status: str = "success",
        note: Optional[str] = None,
    ) -> None:
        entry = pd.DataFrame(
            [
                {
                    "pipeline": pipeline,
                    "rows_in": rows_in,
                    "rows_out": rows_out,
                    "rows_repaired": rows_repaired,
                    "rows_dropped": rows_dropped,
                    "status": status,
                    "note": note,
                    "run_at": pd.Timestamp.utcnow(),
                }
            ]
        )
        self.ensure_own_schema()
        entry.to_sql(
            "etl_runs",
            self.engine,
            schema=self.own_schema,
            if_exists="append",
            index=False,
        )
        log.info(f"Logged run of '{pipeline}' to {self.own_schema}.etl_runs")

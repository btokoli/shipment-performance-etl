# Multi-stage image for the shipment-performance ETL.
#
# Stage 1 installs deps to a user prefix. Stage 2 is a clean slim runtime
# that runs the ETL as a non-root user. The container runs the pipeline
# once and exits zero on success; the smoke sidecar reads the status JSON
# the pipeline writes and asserts on it.

# --- Stage 1: builder --------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# --- Stage 2: runtime --------------------------------------------------------
FROM python:3.12-slim

RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local

# Application code AND the vendored db helper.
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser vendor ./vendor
COPY --chown=appuser:appuser run.py ./run.py

# Create /app/data owned by appuser BEFORE the VOLUME declaration so the
# named volume inherits appuser ownership on first mount. Without this the
# named volume defaults to root-owned and the pipeline fails to write.
RUN mkdir -p /app/data && chown -R appuser:appuser /app/data

USER appuser

ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The pipeline writes status JSON and quarantine.csv to /app/data; the
# compose file mounts a named volume there so the smoke sidecar reads the
# same status the pipeline wrote.
VOLUME ["/app/data"]

CMD ["python", "run.py"]

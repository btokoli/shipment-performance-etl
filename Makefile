# Module 05 class-project: standalone shipment-performance ETL.
# Vendored DB helper at vendor/db.py. Reads .env in this folder. Copy the
# folder to an empty directory and the recipe below works.

.PHONY: install run test build up down logs clean

install:        ## install host deps
	pip install -r requirements.txt

run:            ## run the pipeline against the live logistics data (host)
	python run.py

test:           ## run the unit tests (no database needed)
	python -m pytest -q

build:          ## build the etl image
	docker compose build

up:             ## etl + smoke; smoke asserts on the status JSON
	docker compose up --build --abort-on-container-exit --exit-code-from smoke

down:           ## tear down + remove the etl-data volume
	docker compose down -v

logs:           ## tail etl logs
	docker compose logs -f etl

clean:          ## remove generated outputs and the image
	python -c "import pathlib; [p.unlink() for p in [pathlib.Path('data/quarantine.csv'), pathlib.Path('data/etl_status.json')] if p.exists()]"
	docker image rm shipment-etl:demo 2>/dev/null || true
